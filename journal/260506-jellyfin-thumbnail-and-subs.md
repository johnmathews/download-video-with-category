# 2026-05-06 — Stop sidecar thumbnails leaking into Jellyfin; tighten subtitle capture

## Problem

After a download landed in `youtube/<category>/`, every video in the Jellyfin
library was showing the *same* poster. Root cause was a stray `.jpg` file
beside each `.mkv`: yt-dlp's `--convert-thumbnails jpg` was leaving the
converted file on disk, and the rsync glob in `_ytdl_on_media_vm` was
explicitly shipping `*.jpg` and `*.webp` along with the video. Once two videos
sat in the same category folder, Jellyfin's image scanner promoted one of the
loose images to folder art and applied it to every entry — the well-known
"YouTube videos all share one poster" complaint on the Jellyfin/Emby forums.

The thumbnail is already embedded inside the mkv via `--embed-thumbnail`, so
the sidecar was always redundant — just a cleanup gap.

## Fix

In the remote download script inside `yt.sh`:

1. Removed `jpg` and `webp` from the file list that gets rsynced to the SSD
   staging dir. The list is now `*.{mkv,mp4,json,nfo}` plus `*info.json`.
2. Added an explicit `rm -f "$tmpdir"/*.{jpg,jpeg,png,webp,srt,vtt}` immediately
   before the file list is built — belt-and-braces in case yt-dlp leaves a
   stray image (or sub) under any future flag combination.

The `srt`/`vtt` cleanup also drops sidecar subtitles, which were being staged
even though `--embed-subs` had already merged them into the mkv. Jellyfin
reads embedded subtitle tracks fine, so the loose files were just clutter.

## Subtitle improvements

While in there:

1. Added `--write-subs` alongside the pre-existing `--write-auto-subs`. Without
   it, only auto-generated captions were captured — manually authored English
   subs (which are higher quality when present) were silently skipped.
2. Narrowed `--sub-langs "en.*,nl,de,es"` → `"en.*"`. English-only matches the
   actual library use case and the glob still catches `en`, `en-US`, `en-GB`,
   and `en-orig`.

## Verified

- `zsh -n yt.sh` parses cleanly.
- The embedded `remote_script` (single-quoted heredoc executed on the media VM
  as bash) parses cleanly under `bash -n` after extraction. The first attempt
  at the new comment included an apostrophe ("Jellyfin's") which broke the
  outer single-quoted string — rephrased to avoid it.

## Out of scope / follow-ups

- `info.json` and `nfo` are still staged. They don't break Jellyfin and may be
  useful elsewhere, so leaving them.
- The retry path (download without subtitles when the first call produces no
  video file) is unchanged. It already had no subtitle flags, so it benefits
  automatically from the tighter file list and the `rm -f` cleanup.
