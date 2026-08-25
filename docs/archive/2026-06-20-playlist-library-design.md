**Status:** superseded by [architecture.md](../architecture.md) (2026-08-25). Historical plan/spec for the zsh implementation, which was ported to Python; kept for the design rationale.

# Playlist-as-Jellyfin-Library — Design

**Date:** 2026-06-20
**Status:** approved (pending spec review)
**Component:** `yt.sh`

## Goal

Add a `yt -p <playlist-url>` mode that downloads an entire YouTube playlist, in
order, into its own directory under `/mnt/tank/movies/youtube/<slug>/`. That
directory becomes a new Jellyfin **movie** library (added manually in the
Jellyfin admin UI). Videos are numbered so they sort first-to-last.

This mirrors the existing category model (each category flag → one directory →
one Jellyfin library), but the directory name is derived per-playlist instead of
from a fixed category list.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Directory naming | Auto-detect playlist title → slug, **confirm with override** before downloading |
| Jellyfin library creation | **Manual** in the Jellyfin UI (no API integration) |
| Resume / re-run behavior | yt-dlp `--download-archive` — skip already-downloaded items, cheap re-runs, free resume |
| Playlist size | Medium (tens of videos) → **per-video streaming** (one video in `/tmp` at a time) |
| Jellyfin presentation | **Flat movie library**, index-prefixed filenames (`001-Title.mkv`) |
| Implementation shape | **Approach A** — new `_yt_playlist_on_media_vm` function parallel to the single-video path; do not modify the proven single-video logic beyond extracting a shared transfer helper |

## Invocation & flag parsing

- New flag `-p` / `--playlist` added to the `zparseopts` call (`yt.sh:429`).
- `yt -p <playlist-url>` routes to the playlist path instead of category mapping.
- Mutually exclusive with category flags (`-g -y -c -m -h -t -e --category`):
  error and exit non-zero if a category flag is combined with `-p`.
- Slug resolution:
  1. Fetch the title: `yt-dlp --flat-playlist --playlist-items 1 --print "%(playlist_title)s"`.
  2. Slugify: lowercase, replace each run of non-`[a-z0-9]` with `-`, trim
     leading/trailing `-`.
  3. Print the proposed slug to stderr and prompt:
     `Use directory '<slug>'? [Y/n/edit]`
     - Enter / `y` / `Y` → accept the suggestion.
     - `n` / `N` → abort (exit non-zero, nothing downloaded).
     - any other text → use that text as the directory name, re-slugified.
  4. This interactive prompt is the only deviation from the stderr-only rule;
     it reads from the tty. All other output stays on stderr; per-item final
     paths still go to stdout.

## Per-video download loop

After the slug is confirmed:

1. Upload the cookie to the media VM **once** (reuse current cookie validation
   and atomic `umask 077` upload).
2. Ensure the final dir exists: `/mnt/nfs/movies/youtube/<slug>/`
   (NFS view on the media VM; same underlying tank dataset the NAS-local rsync
   targets).
3. Enumerate the playlist to get the item count and detect an empty/invalid
   playlist early:
   `yt-dlp --flat-playlist --print "%(playlist_index)s" <url>` → count of lines.
   If zero, error and exit.
4. Loop `N = 1 .. count`. For each item, in a single SSH call to the media VM:
   - Create a fresh `/tmp/yt.XXXXXX` and a matching SSD staging subdir.
   - Run `yt-dlp --playlist-items N <playlist-url>` with:
     - `--download-archive /mnt/nfs/movies/youtube/<slug>/archive.txt`
       (skips items already recorded; on a skip yt-dlp writes no file and the
       loop advances).
     - output template `%(playlist_index)03d-%(title)s-[%(id)s].%(ext)s`
       → `001-Title-[id].mkv`, sorting correctly in a flat movie library.
     - the same media flags as the single-video path: `--embed-metadata`,
       `--embed-chapters`, `--embed-thumbnail --convert-thumbnails jpg`,
       English subs (`--sub-langs "en.*" --write-subs --write-auto-subs
       --embed-subs --convert-subs srt …`) with the existing **no-subtitles
       retry fallback**, `-f bestvideo+bestaudio --merge-output-format mkv`,
       `--restrict-filenames`.
     - sidecar image/sub cleanup before staging (as today).
   - Progress to stderr: `[N/count] <title>`.

`--playlist-items N` against the playlist URL (rather than fetching each video
by its own URL) is what makes `%(playlist_index)s` resolve correctly.

## Staging & transfer (sequential, per-video)

Each item runs the **full** existing two-stage staged transfer to completion
before the next item begins downloading:

1. media VM `/tmp/yt.XXXXXX` → SSD NFS staging `yt-staging/<unique>/` (rsync,
   `--remove-source-files`).
2. NAS-local rsync from SSD (`swift`) → HDD (`tank`) `…/youtube/<slug>/`.

Because transfer fully completes per item, `/tmp` holds at most one video, and
an interruption leaves every completed video on the HDD. Item `N+1` does not
start until item `N` has landed (or been skipped/failed).

The two SSH `remote_script` / `nas_script` blocks are factored into a small
shared helper so the single-video and playlist paths use one copy of the
staged-transfer logic. The single-video function keeps its current behavior;
only the transfer blocks are extracted.

## Error handling & resume

- A failed item logs the error to stderr and the loop **continues** to the next
  item — one bad/unavailable video must not abort a long playlist.
- The function returns non-zero if any item failed, after printing a summary:
  `downloaded X, skipped Y, failed Z`.
- The archive records only successful downloads, so re-running
  `yt -p <url>` resumes where it left off and picks up newly-added videos.
- Cookie cleanup and the `INT`/`TERM` trap (removing the *current* item's tmp +
  staging dirs) are preserved. The archive file and already-transferred videos
  are never touched by cleanup.
- On NAS-transfer failure for an item, the existing manual-recovery command is
  printed and that item is counted as failed; the loop continues.

## Output contract

- stderr: all progress, the slug confirmation prompt, the final summary.
- stdout: the final NFS-visible path of each successfully downloaded video,
  `/mnt/nfs/movies/youtube/<slug>/<filename>` (one per line) — same construction
  as the single-video path (`${remote_final_dir}/${basename}`) so piping still
  works.

## Testing

Repo currently has no tests; add a minimal shell test harness alongside this
feature (per the global testing rule).

- **Slug generation:** titles with spaces, punctuation, unicode, leading/
  trailing junk → expected slug.
- **Flag parsing:** `-p` recognized; `-p` + category flag → error;
  `-p` with no URL → error.
- **Confirm prompt:** Enter accepts; `n` aborts; freeform text overrides.
- **Loop behavior:** against a mocked `yt-dlp`/`ssh`, verify N invocations with
  the right `--playlist-items` values, archive path, and output template; verify
  a mid-loop failure continues and is reflected in the summary/exit code.

`yt-dlp`, `ssh`, and the remote filesystem are stubbed; no network or real
hosts are contacted.

## Docs to update

- `readme.md` — new `-p` usage and examples.
- `_yt_show_help` — `-p` / `--playlist` entry and a playlist example.
- `CLAUDE.md` — note the playlist path and the shared transfer helper.
- `journal/` — dated entry capturing the design and decisions.

## Out of scope

- Jellyfin REST API integration (libraries added manually).
- TV-series/episode semantics (`SxxEyy`, autoplay-next).
- Batch (all-at-once) download for very large playlists.
- Per-item quality-upgrade comparison (the single-video ffprobe check);
  `--download-archive` is the playlist dedup mechanism instead.
