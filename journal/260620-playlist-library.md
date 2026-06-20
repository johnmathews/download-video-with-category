# 260620 — Playlist library feature

## Goal

Allow `yt -p <url>` to download an entire YouTube playlist, one video at a time, into its own
directory that can be added as a Jellyfin movie library. Each video should carry a numeric index
prefix so they sort in playlist order, and re-runs should skip already-downloaded items.

## Approach A: separate playlist path, don't disturb single-video path

The single-video path (`_ytdl_on_media_vm`) does duplicate detection via ffprobe, fetches video
info for display, and has a specific output template and duplicate-check logic that doesn't apply
to playlists. Rather than adding branches inside an already-complex function, the playlist
feature lives in its own function (`_yt_playlist_on_media_vm`) with its own item script constant
(`_YT_PLAYLIST_ITEM_SCRIPT`). The stage-2 NAS transfer script (`_YT_NAS_SCRIPT`) is shared
between both paths — it's pure rsync with no path-specific logic.

## Five design decisions

1. **Auto-slug-with-confirm**: The playlist title is fetched from yt-dlp and slugified
   automatically (lowercase ASCII, dashes). The user sees the suggested slug and can accept,
   abort, or type a replacement. This avoids requiring a manual `--name` flag while still giving
   the user control over the directory name.

2. **Manual Jellyfin library**: Each playlist lands in its own directory under
   `/mnt/tank/movies/youtube/<slug>/`. The user adds this directory manually as a Jellyfin movie
   library. Automatic library creation would require Jellyfin API access and ongoing library
   management, which is out of scope. A manual one-time add is low-friction enough.

3. **`--download-archive` resume**: yt-dlp's `--download-archive` flag records downloaded video
   IDs in `archive.txt` alongside the videos. Re-running `yt -p` on the same URL skips already-
   downloaded items instantly. This makes partial runs, interrupted downloads, and periodic syncs
   of growing playlists all trivially safe.

4. **Per-video streaming (sequential loop)**: Each playlist item is downloaded, staged to SSD,
   and transferred to the NAS HDD before the next item begins. This keeps peak disk usage low
   (only one item in staging at a time), simplifies error handling (a failed item logs and
   continues), and produces a running summary at the end. A parallel approach would be faster
   but much harder to reason about and test.

5. **Flat indexed movie library**: Videos use the template
   `%(playlist_index)03d-%(title)s-[%(id)s].%(ext)s` so they sort as `001-...`, `002-...`
   within the flat directory. Jellyfin treats each file as an individual movie. This is simpler
   than a show/episode structure and works well for tutorial series, lectures, and curated
   playlists that don't map naturally to TV seasons.

## Test approach

Tests are written in bats (`tests/playlist.bats`). The `$YT_SSH` environment variable (default
`/usr/bin/ssh`) is replaced with a stub script that echoes controlled responses for each SSH
call without requiring a real remote host. This lets the tests cover the full zsh logic
(slug derivation, prompt handling, item loop, skip/fail/download counting, exit code) without
any network dependency.
