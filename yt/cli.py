"""`yt` entry point: flag parsing and dispatch to the single / playlist / fitness modes."""

from __future__ import annotations

import argparse
import sys

from yt import fitness, playlist, single
from yt.config import CATEGORIES, MEDIA_HOST, REMOTE_FINAL_BASE, VALID_CATEGORIES
from yt.remote_scripts import UPDATE_COMMAND
from yt.ssh import ssh
from yt.ui import Failure, info

# Retired 2026-09-04, superseded by fitness mode (`yt -f`). Still intercepted in run().
RETIRED_CATEGORY = "training"

HELP = """\
yt - Download videos to media VM with categorization

USAGE:
  yt -SHORTCUT URL
  yt --category CATEGORY URL
  yt --update
  yt --help  (or: yt help)

DESCRIPTION:
  Downloads YouTube (and other) videos directly on the media VM and saves them to the correct
  subdirectory in the movies dataset.

  The script copies a youtube cookie from ~/.config/yt-dlp/cookies/cookies.txt (or $LOCAL_YT_COOKIES)
  onto the media VM.
  Use a browser plugin to copy the cookie from a browser to the local config directory.

  The script handles:
    - quality selection
    - duplicate detection
    - metadata embedding
    - destination directory according to category

CATEGORIES:
{categories}

OPTIONS:
  --category CATEGORY    Specify category by name (alternative to shortcuts)
  -p, --playlist URL     Download an entire playlist into its own library dir
  -f, --fitness [Show/Season] URL
                         Add one video to a season of a show in the Jellyfin
                         "Health & Fitness" library (fitness/<Show>/Season NN/).
                         With just a URL it asks which show and season (listing
                         what exists, offering "new"). Season = number | name |
                         N:Name (create), optionally :feed or :course. Writes the
                         SnnEnn filename, .nfo and -thumb.jpg for you.
                         Seasons are "feed" (newest first; episodes count DOWN
                         from 999) or "course" (oldest first; 1, 2, 3…). A season
                         with no order set is asked about once.
  --season-order "Show/Season" [feed|course]
                         Show or set a season's order (writes Season NN/.order).
  --update               Update yt-dlp on the media VM (official standalone binary)
  --help                 Show this help message (also: yt help)

WHICH MODE?
  One video, filed by topic .............. yt -SHORTCUT URL
  A whole playlist as its own library .... yt -p URL
  A gym / workout video for Jellyfin ..... yt -f URL

EXAMPLES:
  yt -y "https://youtu.be/C4TVr2NtEg8"
  yt -m "https://youtube.com/watch?v=dQw4w9WgXcQ"
  yt --category music "https://youtube.com/watch?v=dQw4w9WgXcQ"

  Download a playlist as its own Jellyfin library:
    yt -p "https://www.youtube.com/playlist?list=PLxxxxxxxx"

  Add a video to a season of a show in Health & Fitness:
    yt -f "https://youtu.be/xQqCyl-2ixQ"                             # asks show + season
    yt -f "Kettlebell/Tutorials" "https://youtu.be/xQqCyl-2ixQ"      # by season name
    yt -f "Kettlebell/3" "https://youtu.be/xQqCyl-2ixQ"              # by season number
    yt -f "Kettlebell/4:Swings" "https://youtu.be/..."               # create Season 04 "Swings"
    yt -f "Running/1:Form" "https://youtu.be/..."                    # create a new show too
    yt -f "Kettlebell/4:Swings:course" "https://youtu.be/..."        # create as a course (default for new is asked)
    yt --season-order "Kettlebell/Tutorials" feed                    # make an existing season newest-first

  Update yt-dlp on the media VM:
    yt --update

  Pipe to epm for photo extraction:
    yt -y "https://youtu.be/C4TVr2NtEg8" | epm

REQUIREMENTS:
  - YouTube cookies must be exported to: ~/.config/yt-dlp/cookies/cookies.txt (override: LOCAL_YT_COOKIES)
  - SSH access to 'media' host must be configured
  - yt-dlp must be installed on the media VM

FILES:
  Final videos are saved to: /mnt/nfs/movies/youtube/{{CATEGORY}}/
  Legacy (not written to):   /mnt/nfs/movies/youtube/training/  — see 'yt -f' 
  Playlists are saved to:    /mnt/nfs/movies/youtube/{{PLAYLIST-SLUG}}/
  Fitness episodes go to:    /mnt/nfs/movies/youtube/fitness/{{SHOW}}/Season NN/
  Set JELLYFIN_URL + JELLYFIN_API_KEY to trigger a Jellyfin scan after -f.
"""


def help_text() -> str:
    categories = "\n".join(f"  -{flag}  {name:<17} {desc}" for flag, (name, desc) in CATEGORIES.items())
    return HELP.format(categories=categories)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        info(f"❌ Error: {message}")
        info("Run 'yt --help' for more information")
        raise SystemExit(1)


def build_parser() -> _Parser:
    # add_help=False: `-h` is the shortcut for the *humanity* category, not help.
    parser = _Parser(prog="yt", add_help=False)
    for flag in CATEGORIES:
        parser.add_argument(f"-{flag}", action="store_true", dest=f"cat_{flag}")
    parser.add_argument("--category")
    # Retired, but still parsed: -g is in muscle memory, and argparse's
    # "unrecognized arguments" would not tell anyone to use -f instead.
    parser.add_argument("-g", action="store_true", dest="retired_training")
    parser.add_argument("-p", "--playlist", action="store_true")
    parser.add_argument("-f", "--fitness", action="store_true")
    parser.add_argument("--season-order", action="store_true")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--help", action="store_true")
    parser.add_argument("positional", nargs="*")
    return parser


def _selected_category(args: argparse.Namespace) -> str | None:
    for flag, (name, _) in CATEGORIES.items():
        if getattr(args, f"cat_{flag}"):
            return name
    return args.category or None


def _retired_category_error() -> None:
    """`-g` / `--category training` — superseded by `yt -f` (fitness mode)."""
    info(f"❌ -g / {RETIRED_CATEGORY} is retired.")
    info()
    info('   Gym and workout videos now go to the Jellyfin "Health & Fitness" library:')
    info("     yt -f <url>                       # asks which show and season")
    info('     yt -f "<Show>/<Season>" <url>     # no questions')
    info()
    info(f"   Existing files in {REMOTE_FINAL_BASE}/{RETIRED_CATEGORY}/ are untouched.")
    info("   That directory is legacy: nothing writes to it any more.")
    raise Failure()


def _usage_error(*lines: str) -> None:
    for line in lines:
        info(line)
    info()
    info("Run 'yt --help' for more information")
    raise Failure()


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("--help", "help"):
        sys.stderr.write(help_text())
        return 0
    args = build_parser().parse_intermixed_args(argv)
    if args.help:
        sys.stderr.write(help_text())
        return 0
    positional: list[str] = args.positional
    category = _selected_category(args)

    if args.retired_training or args.category == RETIRED_CATEGORY:
        _retired_category_error()

    if args.update:
        info("🔄 Updating yt-dlp on media VM (official standalone binary -> /usr/local/bin)...")
        return ssh(MEDIA_HOST, UPDATE_COMMAND, capture=False, tty=True).returncode

    if args.season_order:
        return fitness.season_order(positional[0] if positional else "", positional[1] if len(positional) > 1 else "")

    if args.fitness:
        if category or args.playlist:
            info("❌ Error: -f/--fitness cannot be combined with a category or playlist flag")
            raise Failure()
        if not positional:
            info('❌ Error: usage: yt -f <url>   or   yt -f "<Show>/<Season>" <url>')
            raise Failure()
        if len(positional) >= 2:
            return fitness.add_to_show(positional[0], positional[1])
        return fitness.add_to_show("", positional[0])

    if args.playlist:
        if category:
            info("❌ Error: -p/--playlist cannot be combined with a category flag")
            raise Failure()
        if not positional:
            info("❌ Error: playlist URL is required")
            info("Usage: yt -p <playlist-url>")
            raise Failure()
        return playlist.download_playlist(positional[0])

    shortcuts = "|".join(f"-{flag}" for flag in CATEGORIES)
    if not category:
        _usage_error(
            "❌ Error: Category shortcut is required",
            "",
            f"Usage: yt {shortcuts} URL",
            "   or: yt --category CATEGORY URL",
        )
    if category not in VALID_CATEGORIES:
        _usage_error(f"❌ Error: Invalid category '{category}'", "", f"Valid categories: {', '.join(VALID_CATEGORIES)}")
    if not positional:
        _usage_error("❌ Error: URL is required", "", f"Usage: yt {shortcuts} URL")
    assert category is not None
    return single.download_single(category, positional[0])


def main(argv: list[str] | None = None) -> None:
    try:
        code = run(sys.argv[1:] if argv is None else argv)
    except Failure as failure:
        if failure.message:
            info(failure.message)
        code = failure.code
    except KeyboardInterrupt:
        code = 130
    raise SystemExit(code)
