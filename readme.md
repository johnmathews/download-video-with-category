# yt - Download videos to media VM

A shell function that downloads YouTube (and other) videos directly on the media VM via SSH, saving them to categorized
directories on the NFS-mounted movies dataset.

## How it works

1. Copies browser cookies from your Mac to the media VM over SSH
2. Runs yt-dlp on the media VM to download the video to `/tmp` (local disk)
3. Embeds metadata, chapters, thumbnails, and subtitles
4. Stages the finished file to SSD NFS (`swift` pool) via rsync (~552 MB/s)
5. SSHs to the NAS for a local copy from SSD to HDD (`tank` pool) via rsync (~1.6 GB/s)
6. Cleans up temp and staging dirs

Duplicate detection compares video quality via ffprobe and skips downloads when the existing file is equal or better
quality.

## Categories

```
Flag  Name              Description
-g    training          Training and gym/workout videos
-y    youtube           General YouTube content
-c    create            Creative/maker content
-m    music             Music videos and performances
-h    humanity          Humanities and cultural content
-t    travel            Travel videos and vlogs
-e    math+engineering  Math and engineering content
```

Note: `-h` is the shortcut for "humanity", not help. Use `yt --help` for help.

## Usage

```
yt -g "https://youtu.be/C4TVr2NtEg8"
yt -m "https://youtube.com/watch?v=dQw4w9WgXcQ"
yt --category training "https://youtu.be/C4TVr2NtEg8"
yt --update
yt --help
```

## Keeping yt-dlp current

`yt --update` downloads the **official standalone `yt-dlp_linux` binary** into `/usr/local/bin` on
the media VM (it shadows the apt/PPA package, which lags for months — symptoms: HTTP 403 part-way
through a download, "no impersonate target is available"). The same binary is installed by the
proxmox-setup `media_vm` role (`make media t=ytdlp`).

## Piping

Only the final file path is emitted to stdout (all progress and status output goes to stderr). This means `yt` works in
pipelines:

```
yt -g "https://youtu.be/C4TVr2NtEg8" | epm
```

The path is emitted whether the video was freshly downloaded or skipped as a duplicate.

## Health & Fitness (Jellyfin Shows library)

`yt -f` files one video into a **show / season** of the Jellyfin *Health & Fitness* library
(`/mnt/tank/movies/youtube/fitness/<Show>/Season NN/`) instead of a flat category folder:

```
yt -f "https://youtu.be/xQqCyl-2ixQ"                        # asks which show and season
yt -f "Kettlebell/Tutorials" "https://youtu.be/xQqCyl-2ixQ" # fast path: season by name…
yt -f "Kettlebell/3" "https://youtu.be/xQqCyl-2ixQ"         # …or by number
yt -f "Kettlebell/4:Swings" "https://youtu.be/…"            # create Season 04 "Swings"
yt -f "Running/1:Form" "https://youtu.be/…"                 # create a new show with its first season
```

With just a URL it shows the video's title, then lists the existing shows (numbered, plus
`n) new show`), then that show's seasons with episode counts (plus `n) new season`), then asks
`Add '<title>' there? [Y/n]`. Answer with a number or a name; Enter accepts the default.

What it does for you:

- picks the **next episode number** in that season and names the file
  `<Show> SnnEnn - <uploader>-<title>-[<id>].mkv` (Jellyfin reads season/episode from `SnnEnn`);
- writes the episode **`.nfo`** (title, cleaned description with `Channel · date` header, aired
  date, sort title, YouTube id) and the **`-thumb.jpg`** via `jellyfin_nfo.py`, which is shipped
  to the media VM over stdin (python3, stdlib only);
- creates the show (`tvshow.nfo`) and/or season (`season.nfo` with the name) when you choose
  "new";
- refuses duplicates already anywhere in that show (by YouTube id);
- if `JELLYFIN_URL` and `JELLYFIN_API_KEY` are set, asks Jellyfin to scan now; otherwise the
  scheduled scan picks it up.

**Feed vs course seasons.** Every season has an *order*, kept in `Season NN/.order`:

- `course` — oldest first, episodes numbered 1, 2, 3… (playlist-style tutorials; the default);
- `feed` — newest first: episodes are numbered **down from 999** (first video E999, next E998 …)
  so the latest addition always sorts to the top without renaming anything already there.
  Jellyfin has no "descending" switch, hence the numbering trick; the visible numbers are large.

`yt -f` shows the order next to each season, asks `Order — [f]eed / [c]ourse` when you create a
season (default feed) or the first time you add to a season that has no marker yet, and
`yt --season-order "Kettlebell/Tutorials" feed` sets or shows it explicitly (also accepted inline:
`yt -f "Kettlebell/4:Swings:course" <url>`). Switching an existing ascending season to `feed`
only affects *new* episodes; renumbering the existing ones is the one-off `migrate.py
reorder-season` in proxmox-setup.

Show/season artwork is **not** made here — after creating a season or show, run `make_posters.py`
in the `proxmox-setup` repo (see its `documentation/jellyfin_health_fitness_library.md`, which is
the canonical description of the library's layout and rules).

## Playlists

Download an entire YouTube playlist into its own directory:

```
yt -p "https://www.youtube.com/playlist?list=PLxxxxxxxx"
```

After fetching the playlist title, `yt` derives a URL-safe slug (e.g. `my-playlist-name`) and
prompts you to confirm or override it:

```
Use directory 'my-playlist-name'? [Y/n/edit]:
```

Press Enter (or `y`) to accept, `n` to abort, or type any string to use that as the slug instead.

Each playlist becomes its own directory under `/mnt/tank/movies/youtube/<slug>/` on the NAS. Add
that directory manually as a Jellyfin **movie** library so every video shows up as an individual
movie entry.

Videos are named with a three-digit index prefix (`001-title-[id].mkv`, `002-...`) so they sort in
playlist order on disk. The same index is also embedded into the file's **title metadata** (e.g.
`001 - Original Title`) via yt-dlp's `--parse-metadata`/`meta_title`, so Jellyfin keeps playlist
order even when it sorts by the metadata "Name" rather than the filename. (Up to 999 items the
zero-padded prefix sorts correctly; beyond that the padding would need widening.)

> **Jellyfin note:** by default Jellyfin derives the display Name from the *filename* (which already
> carries the `001-` prefix), so ordering works out of the box. The embedded-title prefix only
> matters if the library has **"Prefer embedded titles over filenames"** enabled. The embedded
> prefix exists only on files downloaded after this feature was added — older files have an
> un-prefixed embedded title, so enabling that setting would require re-downloading (or re-tagging)
> them to keep order.

Re-runs are safe and cheap: `yt-dlp --download-archive` records every downloaded video ID in
`/mnt/nfs/movies/youtube/<slug>/archive.txt`. Already-downloaded items are skipped instantly;
only new or missing items are fetched. This makes it easy to resume an interrupted run or
periodically sync a growing playlist.

Each video is fully transferred to the NAS HDD before the next one begins.

## Updating yt-dlp

If downloads fail (especially with format selection errors), yt-dlp on the media VM likely needs updating:

```
yt --update
```

This runs `sudo apt update && sudo apt install --only-upgrade yt-dlp` on the media VM via SSH. A TTY is allocated for the
sudo prompt.

The script will also suggest this when it can't fetch video info or when a download fails.

## Setup

Source the script in your shell profile:

```sh
source "$HOME/projects/photo-video/download-video/yt.sh"
```

## Two-stage SSD-staged transfer

The transfer uses two stages to maximize throughput:

1. **Media VM → SSD NFS** (`/tmp` → `/mnt/nfs/downloads/yt-staging/`): rsync over NFS at ~552 MB/s (~4s for 2 GB)
2. **NAS-local SSD → HDD** (`swift` → `tank`): rsync on the NAS itself at ~1.6 GB/s (~1.3s for 2 GB)

The Mac orchestrates both stages via separate SSH calls — one to `media`, one to `nas`. Total transfer time for a 2 GB
file is ~5 seconds, down from ~40 seconds with the previous single-stage rsync from `/tmp` directly to HDD NFS.

Each download gets a unique staging subdir (e.g. `yt-staging/yt.a1b2c3`) derived from the `/tmp` tempdir name, so
concurrent downloads don't collide.

If the NAS transfer fails, files remain safe on the SSD staging dir and the error message includes a manual recovery
command. There is no silent fallback to a slow path.

**Why not simpler approaches:**
- **rsync directly to HDD NFS** (the old approach) — only ~50 MB/s, ~40s for 2 GB
- **Download directly to HDD NFS** — slower mux due to NFS latency and HDD random I/O
- **`mv` between NFS mounts from media VM** — sends data over the network twice (NAS→VM→NAS)

## Requirements

- SSH access to `media` host (configured in `~/.ssh/config`)
- SSH access to `nas` host (configured in `~/.ssh/config`) — for the NAS-local SSD→HDD transfer
- YouTube cookies exported to `~/.config/yt-dlp/cookies/cookies.txt` (Netscape cookies.txt format, use a browser
  extension)
- yt-dlp installed on the media VM
- ffprobe on the media VM (for duplicate quality comparison)
