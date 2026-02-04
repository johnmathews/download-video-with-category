# yt - Download videos to media VM

A shell function that downloads YouTube (and other) videos directly on the media VM via SSH, saving them to categorized directories on the NFS-mounted movies dataset.

## How it works

1. Copies browser cookies from your Mac to the media VM over SSH
2. Runs yt-dlp on the media VM to download the video
3. Embeds metadata, chapters, thumbnails, and subtitles
4. Moves the finished file to `/mnt/nfs/movies/youtube/{category}/`
5. Cleans up temp files on the media VM

Duplicate detection compares video quality via ffprobe and skips downloads when the existing file is equal or better quality.

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

Only the final file path is emitted to stdout (all progress and status output goes to stderr). This means `yt` works in pipelines:

```
yt -g "https://youtu.be/C4TVr2NtEg8" | epm
```

The path is emitted whether the video was freshly downloaded or skipped as a duplicate.

## Updating yt-dlp

If downloads fail (especially with format selection errors), yt-dlp on the media VM likely needs updating:

```
yt --update
```

This runs `sudo apt update && sudo apt install --only-upgrade yt-dlp` on the media VM via SSH. A TTY is allocated for the sudo prompt.

The script will also suggest this when it can't fetch video info or when a download fails.

## Setup

Source the script in your shell profile:

```sh
source "$HOME/projects/photo-video/download-video/yt.sh"
```

## Requirements

- SSH access to `media` host (configured in `~/.ssh/config`)
- YouTube cookies exported to `~/.config/yt-dlp/cookies/cookies.txt` (Netscape cookies.txt format, use a browser extension)
- yt-dlp installed on the media VM
- ffprobe on the media VM (for duplicate quality comparison)
