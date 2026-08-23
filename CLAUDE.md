# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A single zsh script (`yt.sh`) that downloads videos via yt-dlp on a remote "media" VM over SSH, then stores them on an NFS-mounted dataset organized by category. It is sourced into the user's shell from `~/.zshrc` and provides the `yt` command.

## Architecture

```
Mac (local)                   Media VM (SSH)                  NAS (SSH)
───────────                   ──────────────                  ─────────
yt() parses flags/URL         yt-dlp downloads video
  → validates cookies         /tmp/yt.XXXXXX (local disk)
  → uploads cookies via SSH          │
  → fetches video info               ▼ rsync (~552 MB/s)
  → checks for duplicates    /mnt/nfs/downloads/yt-staging/   ← SSD (swift pool)
  → SSH to media: download              │
  → SSH to nas: local copy              ▼ rsync (~1.6 GB/s)
  → emits final path                               /mnt/tank/movies/youtube/{category}/
                                                      ← HDD (tank pool)
```

**Key design rule:** all status/progress goes to stderr; only the final file path goes to stdout. This makes `yt` pipeline-friendly (e.g., `yt -g URL | epm`).

Functions defined:
- `yt()` — public entry point, parses flags with `zparseopts`, maps shortcut flags to category names; routes `-p`/`--playlist` to `_yt_playlist_on_media_vm()` and `-f`/`--fitness` to `_yt_fitness_on_media_vm()`
- `_yt_fitness_on_media_vm()` — fitness path (Jellyfin *Health & Fitness* Shows library): cookie upload, video info, interactive show/season picker (`_yt_fitness_pick_target()`) unless `"<Show>/<Season>"` was given, remote resolve of the season dir + next episode number (`_YT_FITNESS_RESOLVE_SCRIPT`), duplicate check across the show, confirm, download+rename to `<Show> SnnEnn - …-[id].mkv` (`_YT_FITNESS_ITEM_SCRIPT`), nfo + thumb via `jellyfin_nfo.py` piped to the media VM's python3, two-stage transfer into `fitness/<Show>/Season NN/`, optional Jellyfin scan (`JELLYFIN_URL`/`JELLYFIN_API_KEY`)
- `_yt_fitness_pick_target()` — the questions (shows list → seasons list → new names); answers on stdin, prompts on stderr, prints `Show/Spec`; `YT_FITNESS_ANSWERS_FROM_STDIN=1` lets tests drive it without a tty
- `_ytdl_on_media_vm()` — single-video path: cookie upload, info fetch, duplicate detection, remote download, two-stage transfer
- `_yt_playlist_on_media_vm()` — playlist path: cookie upload once, slug confirm/override prompt, per-item streaming download loop using `_YT_PLAYLIST_ITEM_SCRIPT`, two-stage transfer per item via `_YT_NAS_SCRIPT`
- `_yt_slugify()` — converts a playlist title to a lowercase dash-separated directory name
- `_yt_show_help()` — help text

Shell-level constants hold heredoc scripts that are piped to `bash -s` over SSH:
- `_YT_NAS_SCRIPT` — stage-2 NAS-local SSD→HDD rsync; shared by all paths
- `_YT_PLAYLIST_ITEM_SCRIPT` — stage-1 per-item yt-dlp download + SSD staging for the playlist path
- `_YT_FITNESS_LIST_SCRIPT` / `_YT_FITNESS_RESOLVE_SCRIPT` / `_YT_FITNESS_ITEM_SCRIPT` — fitness path: list shows/seasons (reads `season.nfo` titles), resolve or create the season dir and compute the next `SnnEnn`, download+rename+stage
- `jellyfin_nfo.py` (a real file next to `yt.sh`, located via `$_YT_DIR`) — piped to `python3 -` on the media VM after staging; writes the episode `.nfo` and renames the thumbnail. Its description cleaner is a copy of `clean_overview()` in proxmox-setup's `scripts/jellyfin-fitness-migration/migrate.py` — keep them in step.

Only the playlist and fitness paths use `$YT_SSH` consistently (and are therefore bats-testable); the single-video path still calls `/usr/bin/ssh` directly.

The SSH binary is configurable via `$YT_SSH` (default `/usr/bin/ssh`). Tests stub this variable to intercept all remote calls without a real SSH connection.

## Shell Conventions

- **zsh-only** — uses `zparseopts`, `setopt local_options pipefail`, zsh array syntax `${(@f)...}`, `${(ie)...}`
- SSH commands go through `$YT_SSH` (defaults to `/usr/bin/ssh`) with `-o BatchMode=yes`
- All variables embedded in SSH commands are escaped with `printf '%q'`
- Signal traps clean up remote temp dirs on INT/TERM
- Cookie files get restrictive permissions via `umask 077`

## Two-Stage SSD-Staged Transfer

The script uses a two-stage transfer orchestrated by two SSH calls from the Mac:

1. **Media VM → SSD NFS**: rsync from `/tmp` to `/mnt/nfs/downloads/yt-staging/` (~552 MB/s). The SSD NFS mount (`swift` pool) is fast enough that this is nearly instant.
2. **NAS-local SSD → HDD**: SSH to `nas`, rsync from `/mnt/swift/downloads/yt-staging/` to `/mnt/tank/movies/youtube/{category}/` (~1.6 GB/s). This is a local copy on the NAS — no network involved.

Each download gets a unique staging subdir derived from the `/tmp` tempdir name (e.g. `yt.a1b2c3`). On NAS failure, files remain on the SSD staging dir with a manual recovery command printed — no silent fallback.

## Adding a New Category

1. Add the flag mapping in `yt()` (around line 414) and in the `zparseopts` call (line 403)
2. Add the category name to the `valid_categories` array (line 393)
3. Add to `_yt_show_help()` categories section
4. Update `readme.md`

Note: playlists (`-p`/`--playlist`) are a separate code path in `_yt_playlist_on_media_vm()` and do not use `valid_categories`. The playlist slug is derived from the playlist title at runtime and confirmed interactively — there is no predefined list to extend.

## Testing

```
bats tests/
```

`tests/fitness.bats` stubs `$YT_SSH` and discriminates the three media-VM `bash -s` scripts by their stdin content; `tests/jellyfin_nfo.bats` runs the helper on a fixture staging dir.

Tests use a stubbed `$YT_SSH` to intercept all remote calls. No real SSH connection is required.
