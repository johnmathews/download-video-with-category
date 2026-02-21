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

## Piping

Only the final file path is emitted to stdout (all progress and status output goes to stderr). This means `yt` works in
pipelines:

```
yt -g "https://youtu.be/C4TVr2NtEg8" | epm
```

The path is emitted whether the video was freshly downloaded or skipped as a duplicate.

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
