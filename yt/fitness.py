"""Fitness mode: `yt -f [Show/Season] URL` — one video into a season of a Jellyfin *Health & Fitness* show.

Layout on disk: fitness/<Show>/Season NN/<Show> SnnEnn - <uploader>-<title>-[id].mkv (+ .nfo, -thumb.jpg).
Seasons carry a `.order` marker: `course` = oldest first (1, 2, 3…), `feed` = newest first
(numbered down from 999 so the latest addition sorts to the top).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

from yt.config import (
    FITNESS_SUBDIR,
    MEDIA_HOST,
    NAS_FINAL_BASE,
    REMOTE_FINAL_BASE,
    jellyfin_credentials,
    nfo_helper_path,
)
from yt.cookies import check_cookies, check_ytdlp_installed
from yt.remote_scripts import FITNESS_ITEM_SCRIPT, FITNESS_LIST_SCRIPT, FITNESS_RESOLVE_SCRIPT
from yt.session import Session
from yt.ssh import id_glob, q, run_script, ssh
from yt.ui import Failure, emit, info, interactive, prompt

ORDERS = ("feed", "course")


@dataclass(frozen=True)
class SeasonInfo:
    show: str
    number: int
    title: str
    episodes: int
    order: str


@dataclass(frozen=True)
class Resolved:
    show_dir: str
    season_dir: str
    episode: int
    width: int
    order: str
    order_missing: bool

    @property
    def season_number(self) -> int:
        return int(self.season_dir.rsplit("/Season ", 1)[-1])

    @property
    def season_name(self) -> str:
        return self.season_dir.rsplit("/", 1)[-1]

    @property
    def code(self) -> str:
        return f"S{self.season_number:02d}E{self.episode:0{self.width}d}"


def parse_listing(listing: str) -> tuple[list[str], dict[tuple[str, int], SeasonInfo]]:
    """FITNESS_LIST_SCRIPT output → (shows in order, seasons keyed by (show, number))."""
    shows: list[str] = []
    seasons: dict[tuple[str, int], SeasonInfo] = {}
    for line in listing.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        parts += [""] * (5 - len(parts))
        show, num, title, count, order = parts[:5]
        if show not in shows:
            shows.append(show)
        if num:
            seasons[(show, int(num))] = SeasonInfo(show, int(num), title, int(count or 0), order or "course")
    return shows, seasons


def _ask(question: str) -> str:
    answer = prompt(question)
    if answer is None:
        raise Failure()
    return answer.strip()


def ask_order(default: str) -> str:
    """feed/course question; Enter takes the default."""
    while True:
        answer = _ask(f"Order — [f]eed (newest first) / [c]ourse (oldest first) [{default[0]}]: ").lower()
        if not answer:
            answer = default[0]
        if answer in ("f", "feed"):
            return "feed"
        if answer in ("c", "course"):
            return "course"
        info("  ? f or c")


def pick_target(listing: str) -> tuple[str, str | None]:
    """Interactive show → season picker. Returns ('Show/spec', order-for-a-new-season or None)."""
    shows, seasons = parse_listing(listing)

    info()
    info("Shows in Health & Fitness:")
    for i, show in enumerate(shows, 1):
        info(f"  {i:2d}) {show}")
    info("   n) new show")
    picked_show = ""
    new_show = False
    while not picked_show:
        answer = _ask("Show [number, name or n]: ")
        if answer in ("n", "N"):
            answer = _ask("New show name: ")
            if not answer:
                continue
            try:
                picked_show, new_show = safe_show_name(answer), True
            except Failure:
                continue
        elif answer.isdigit() and 1 <= int(answer) <= len(shows):
            picked_show = shows[int(answer) - 1]
        else:
            for show in shows:
                if show.lower() == answer.lower():
                    picked_show = show
            if not picked_show:
                info(f"  ? no such show: {answer}")

    nums = [] if new_show else sorted(num for (show, num) in seasons if show == picked_show)
    if nums:
        info()
        info(f"Seasons of {picked_show}:")
        for num in nums:
            season = seasons[(picked_show, num)]
            info(f"  {num:2d}) {season.title} ({season.episodes} episodes, {season.order})")
        info("   n) new season")
    else:
        info()
        info(f"{picked_show} has no seasons yet — the first one will be Season 01.")
    next_num = nums[-1] + 1 if nums else 1

    picked_spec = ""
    new_order: str | None = None
    while not picked_spec:
        answer = _ask("Season [number, name or n]: ") if nums else "n"
        if answer in ("n", "N"):
            answer = _ask(f"New season name (Season {next_num:02d}): ")
            if not answer:
                continue
            picked_spec = f"{next_num}:{answer}"
            new_order = ask_order("feed")
        elif answer.isdigit() and int(answer) in nums:
            picked_spec = answer
        else:
            for num in nums:
                if seasons[(picked_show, num)].title.lower() == answer.lower():
                    picked_spec = str(num)
            if not picked_spec:
                info(f"  ? no such season: {answer}")
    return f"{picked_show}/{picked_spec}", new_order


def resolve(fitness_base: str, show: str, spec: str, set_order: str) -> Resolved | None:
    """Stage 0 on the media VM: season dir + next episode number (creating show/season for N:Name)."""
    result = run_script(MEDIA_HOST, FITNESS_RESOLVE_SCRIPT, fitness_base, show, spec, set_order)
    if result.returncode != 0:
        return None
    parts = result.stdout.splitlines()
    if len(parts) < 4 or not parts[1] or not parts[2].isdigit():
        info(f"❌ Unexpected resolve output: {result.stdout}")
        return None
    parts += [""] * (6 - len(parts))
    return Resolved(
        show_dir=parts[0],
        season_dir=parts[1],
        episode=int(parts[2]),
        width=int(parts[3]) if parts[3].isdigit() else 2,
        order=parts[4] or "course",
        order_missing=parts[5] == "1",
    )


def safe_show_name(name: str) -> str:
    """A show name that is safe to use as a directory name under the fitness tree.

    The show is the *only* user-supplied path component — season directories are
    always "Season NN" and episode names are built from the resolved numbers — so
    this is the whole traversal surface. Real library names include
    "Mobility & Physio" and "Combat Sports", so spaces, "&" and non-ASCII must all
    survive; only path-significant forms are rejected.
    """
    cleaned = name.strip()
    if not cleaned or "/" in cleaned or cleaned.startswith((".", "-")) or any(c in cleaned for c in "\0\n\r"):
        info(f"❌ {name!r} is not a usable show name")
        info("   A show becomes a directory in the fitness library:")
        info("   no '/', no leading '.' or '-', and not empty.")
        raise Failure()
    return cleaned


def split_target(target: str) -> tuple[str, str, str]:
    """'Show/spec[:feed|course]' → (show, spec, order-or-''). Validates the show."""
    show, spec = target.split("/", 1)
    show = safe_show_name(show)
    order = ""
    for candidate in ORDERS:
        if spec.endswith(":" + candidate):
            order = candidate
            spec = spec[: -len(candidate) - 1]
    return show, spec, order


def _fetch_info(cookie: str, url: str) -> tuple[str, str, str]:
    result = ssh(
        MEDIA_HOST,
        "yt-dlp --remote-components ejs:github --print '%(id)s' --print '%(title)s' --print '%(uploader)s' "
        f"--cookies {q(cookie)} {q(url)} 2>/dev/null",
    )
    parts = result.stdout.splitlines()
    if result.returncode != 0 or len(parts) < 3:
        return "unknown", "Unknown Video", "?"
    return parts[0], parts[1], parts[2]


def _find_in_show(show_dir: str, video_id: str) -> str:
    result = ssh(
        MEDIA_HOST,
        f"find {q(show_dir)} -type f \\( -name '*.mkv' -o -name '*.mp4' \\) -name {q(id_glob(video_id))} "
        "2>/dev/null | head -1",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def request_jellyfin_scan() -> None:
    creds = jellyfin_credentials()
    if creds is None:
        info("ℹ️  Jellyfin picks it up on the next scheduled scan (set JELLYFIN_URL + JELLYFIN_API_KEY to scan now)")
        return
    url, key = creds
    request = urllib.request.Request(
        f"{url}/Library/Refresh", method="POST", headers={"Authorization": f'MediaBrowser Token="{key}"'}
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (urllib.error.URLError, OSError):
        info("⚠️  Jellyfin scan request failed (JELLYFIN_URL/JELLYFIN_API_KEY); the scheduled scan will pick it up")
        return
    info("🔄 Jellyfin library scan requested")


def add_to_show(target: str, url: str) -> int:
    """`yt -f [Show/Season] URL`. Empty target → interactive picker."""
    if target and "/" not in target:
        info(f"❌ Target must be <Show>/<Season>, got: {target}")
        raise Failure()
    helper = nfo_helper_path()
    if not helper.is_file():
        info(f"❌ nfo helper not found: {helper}")
        raise Failure()
    cookies = check_cookies()
    check_ytdlp_installed()
    fitness_base = f"{REMOTE_FINAL_BASE}/{FITNESS_SUBDIR}"
    if target:
        split_target(target)  # reject an unusable show before opening a remote session

    with Session().open() as session:
        session.upload_cookie(cookies)

        info(f"🔍 [{session.elapsed}] Fetching video info...")
        video_id, title, uploader = _fetch_info(session.cookie, url)
        info()
        info(f"📹 {title}  ({uploader})  [{video_id}]")

        set_order = ""
        if not target:
            if not interactive():
                info('❌ No <Show>/<Season> given and stdin is not a terminal — use: yt -f "<Show>/<Season>" <url>')
                session.cleanup(staging=False)
                raise Failure()
            listing = run_script(MEDIA_HOST, FITNESS_LIST_SCRIPT, fitness_base).stdout
            if not listing:
                info(
                    f"⚠️  Could not list existing shows under {fitness_base} (is the media VM's NFS mount up?) "
                    "— only 'new show' is offered"
                )
            try:
                target, new_order = pick_target(listing)
            except Failure:
                info("Aborted — nothing downloaded.")
                session.cleanup(staging=False)
                raise
            set_order = new_order or ""
        show, spec, inline_order = split_target(target)
        set_order = inline_order or set_order

        resolved = resolve(fitness_base, show, spec, set_order)
        if resolved is None:
            info(f"❌ Could not resolve {target} under {fitness_base}")
            session.cleanup(staging=False)
            raise Failure()

        # No .order marker yet on an existing season: ask once, write it, re-resolve (numbering depends on it).
        if resolved.order_missing and interactive():
            info()
            info(f"ℹ️  {resolved.season_name} of {show} has no order set yet.")
            try:
                set_order = ask_order("course")
            except Failure:
                set_order = "course"
            resolved = resolve(fitness_base, show, spec, set_order) or resolved

        if video_id != "unknown":
            existing = _find_in_show(resolved.show_dir, video_id)
            if existing:
                info(f"⏭️  Already in this show: {existing.removeprefix(fitness_base + '/')}")
                emit(existing)
                session.cleanup(staging=False)
                return 0

        info()
        info(f"📁 {show} / {resolved.season_name} ({resolved.order})  →  {resolved.code}")
        if interactive():
            go = prompt(f"Add '{title}' there? [Y/n]: ")
            if go not in ("", "y", "Y"):
                info("Aborted — nothing downloaded.")
                session.cleanup(staging=False)
                raise Failure()
        info()

        # Stage 1: download + rename + stage to SSD.
        result = run_script(
            MEDIA_HOST,
            FITNESS_ITEM_SCRIPT,
            session.tmpdir,
            session.cookie,
            session.staging_dir,
            url,
            show,
            resolved.season_number,
            resolved.episode,
            resolved.width,
        )
        if result.returncode != 0:
            info("❌ Remote download failed")
            session.cleanup()
            raise Failure()
        basenames = [line for line in result.stdout.splitlines() if line]
        info(f"⏱️  [{session.elapsed}] Download + SSD staging complete")

        # Stage 1b: write the episode .nfo and name the thumbnail, in the staging dir.
        # capture=True is load-bearing: the helper prints every sidecar it wrote, and
        # with capture=False those paths inherit yt's stdout and land there ahead of the
        # real video path, which breaks `yt -f URL | epm`. Its output is progress, so
        # it belongs on stderr like every other status line.
        nfo = ssh(
            MEDIA_HOST,
            f"python3 - {q(session.staging_dir)} {q(show)} {q(resolved.season_number)} {q(resolved.episode)}",
            stdin=helper.read_text(),
            capture=True,
        )
        for written in nfo.stdout.splitlines():
            if written:
                info(f"   📝 {written}")
        if nfo.returncode != 0:
            info(f"❌ nfo generation failed — files are on SSD staging: {session.staging_dir}")
            raise Failure()

        # Stage 2: NAS-local SSD -> HDD into the season dir.
        # str.removeprefix is a no-op when the prefix is absent, which would silently
        # turn season_rel into an absolute path and send rsync somewhere unintended.
        if not resolved.season_dir.startswith(fitness_base + "/"):
            info(f"❌ Resolved season dir is outside {fitness_base}: {resolved.season_dir}")
            info(f"   Files are on SSD staging: {session.staging_dir}")
            raise Failure()
        season_rel = resolved.season_dir.removeprefix(fitness_base + "/")
        nas_season_dir = f"{NAS_FINAL_BASE}/{FITNESS_SUBDIR}/{season_rel}"
        info(f"📀 [{session.elapsed}] Transferring to HDD on NAS...")
        if not session.nas_transfer(nas_season_dir):
            info(f"❌ NAS transfer failed — files remain on SSD staging: {session.nas_staging_dir}")
            raise Failure()

        info(f"✅ [{session.elapsed}] Added to {resolved.season_dir}")
        for name in basenames:
            emit(f"{resolved.season_dir}/{name}")

        request_jellyfin_scan()
        if resolved.episode == 1:
            info("🖼️  First episode of this season — re-run make_posters.py (proxmox-setup) for its thumbcards")
        return 0


def season_order(target: str, order: str) -> int:
    """`yt --season-order "Show/Season" [feed|course]` — show or set a season's order."""
    if not target or "/" not in target:
        info('Usage: yt --season-order "<Show>/<Season>" [feed|course]')
        raise Failure()
    if order not in ("", *ORDERS):
        info("❌ order must be feed or course")
        raise Failure()
    fitness_base = f"{REMOTE_FINAL_BASE}/{FITNESS_SUBDIR}"
    show, spec, _ = split_target(target)
    resolved = resolve(fitness_base, show, spec, order)
    if resolved is None:
        info(f"❌ Could not resolve {target}")
        raise Failure()
    info(f"{show} / {resolved.season_name}: order={resolved.order}, next episode {resolved.code}")
    if resolved.order == "feed":
        info(
            "   (feed = newest first: episodes count down from 999; existing ascending seasons need the "
            "one-off reorder-season in proxmox-setup)"
        )
    return 0
