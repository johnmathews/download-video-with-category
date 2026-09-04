# Architecture

> Purpose: how `yt` moves a video from YouTube to the NAS, and where each piece of the code lives.

## 1. Data flow

```
Mac (local)                   Media VM (SSH)                  NAS (SSH)
───────────                   ──────────────                  ─────────
yt parses flags/URL           yt-dlp downloads video
  → validates cookies         /tmp/yt.XXXXXX (local disk)
  → uploads cookies via SSH          │
  → fetches video info               ▼ rsync (~552 MB/s)
  → checks for duplicates    /mnt/nfs/downloads/yt-staging/   ← SSD (swift pool)
  → SSH to media: download              │
  → SSH to nas: local copy              ▼ rsync (~1.6 GB/s)
  → emits final path                               /mnt/tank/movies/youtube/{category}/
                                                      ← HDD (tank pool)
```

**Key rule:** all status/progress goes to stderr; only final file paths go to stdout. This makes `yt`
pipeline-friendly (`yt -y URL | epm`).

## 2. Two-stage SSD-staged transfer

1. **Media VM → SSD NFS**: the remote download script rsyncs from `/tmp` to
   `/mnt/nfs/downloads/yt-staging/<subdir>` (~552 MB/s, ~4 s for 2 GB).
2. **NAS-local SSD → HDD**: `yt` SSHes to `nas` and runs `NAS_SCRIPT`, an rsync from
   `/mnt/swift/downloads/yt-staging/<subdir>` to `/mnt/tank/movies/youtube/...` (~1.6 GB/s, ~1.3 s for 2 GB).

Each download gets a unique staging subdir derived from the `/tmp` tempdir name (e.g. `yt.a1b2c3`) so
concurrent downloads don't collide. If stage 2 fails, the files stay on SSD staging so they can be recovered by
hand — there is no silent fallback to a slow path. Single-video mode prints the exact `rsync`/`rmdir` commands to
finish the transfer; playlist and fitness mode print only the staging path.

Why not simpler approaches: rsync directly to HDD NFS was ~50 MB/s (~40 s for 2 GB); downloading directly to
HDD NFS makes the mux slow; `mv` between NFS mounts from the media VM sends the data over the network twice.

## 3. Package layout (`yt/`)

| Module | Role |
|---|---|
| `cli.py` | Flag parsing (`-y -c -m -h -t -e`, `--category`, `-p`, `-f`, `--season-order`, `--update`, `--help`; a bare `help` word also shows help) and dispatch. `-h` is the *humanity* shortcut, not help. `-g` is still parsed but retired — it prints a pointer to `yt -f` and exits 1. |
| `config.py` | Hosts, NFS/NAS paths, category table, and the environment overrides (`LOCAL_YT_COOKIES`, `YT_SSH`, `YT_NFO_HELPER`, `JELLYFIN_URL`/`JELLYFIN_API_KEY`, `YT_FITNESS_ANSWERS_FROM_STDIN`). |
| `ssh.py` | The one place that spawns `ssh`. `ssh()` runs a command with `BatchMode=yes`; `run_script()` pipes a bash script to `bash -s -- args…` with every argument `shlex.quote`d; `remove_remote()` is best-effort cleanup. Tests replace `_execute`. |
| `remote_scripts.py` | The bash that runs *on* the media VM / NAS, as string constants: `NAS_SCRIPT`, `SINGLE_ITEM_SCRIPT`, `PLAYLIST_ITEM_SCRIPT`, `FITNESS_LIST_SCRIPT`, `FITNESS_RESOLVE_SCRIPT`, `FITNESS_ITEM_SCRIPT`, `UPDATE_COMMAND`. Kept as shell because yt-dlp, rsync and the mounts live there; they take positional arguments only. |
| `cookies.py` | Cookie-file preflight (missing / empty / older than 7 days), the `yt-dlp` presence check on the media VM, and upload under `umask 077`. |
| `session.py` | `Session`: `mktemp` on the media VM, the derived staging dirs, cookie upload, `nas_transfer()`, and cleanup. Used as a context manager: a `KeyboardInterrupt` inside the block removes the remote tmp and staging dirs and exits 130 (the zsh `trap`). |
| `single.py` | `yt -y URL`: info fetch, duplicate check by `[id]` with ffprobe quality comparison, download, two-stage transfer. Refuses the comparison when either quality is unknown rather than assuming the existing file is better. |
| `playlist.py` | `yt -p URL`: slug confirmation, per-item loop with `--download-archive`, downloaded/skipped/failed accounting. |
| `fitness.py` | `yt -f`: interactive show/season picker, resolve on the media VM (season dir, next episode number, feed/course order), download + `SnnEnn` rename, nfo via `jellyfin_nfo.py`, optional Jellyfin scan; `--season-order`. |
| `jellyfin_nfo.py` | Stdlib-only script shipped over stdin to the media VM's `python3 -`; writes the episode `.nfo` and renames the thumbnail. Must not import from `yt`. Its `clean_overview()` is a copy of the one in proxmox-setup's `migrate.py` — keep them in step. |
| `ui.py` | `info()` (stderr), `emit()` (stdout), `prompt()`, `interactive()` (tty, or `YT_FITNESS_ANSWERS_FROM_STDIN`), `Elapsed`, `format_size()`, and the `Failure` exception the CLI turns into an exit code. |

The playlist library design that this document superseded is kept in
[docs/archive/](archive/) — `2026-06-20-playlist-library-design.md` records why playlist mode
auto-slugs with a confirm prompt and is framed as a movie library.

## 4. Remote-script contracts

Every remote script gets its inputs as `bash -s -- arg1 arg2 …` positional parameters, and `ssh.run_script()`
quotes every one of them — for scripts, quoting really is handled in one place.

**Ad-hoc `ssh()` command strings are the exception and must quote their own values.** Roughly eight call sites
build a command with an f-string; every embedded value there has to go through `ssh.q()`, and a value used as a
`find -name` pattern also needs `ssh.id_glob()` so brackets stay literal. This paragraph used to claim the Python
side never interpolates at all, which was not true of those call sites and is why two of them shipped an
unquoted video id.

- Stage-1 download scripts print **video basenames** on stdout, one per line, and nothing else; the Mac
  builds the NFS-visible final paths from them.
- `PLAYLIST_ITEM_SCRIPT` exits 0 with no output for an archived skip and **3** for a genuine yt-dlp failure, so
  the loop can count them separately.
- `FITNESS_RESOLVE_SCRIPT` prints six lines: show dir, season dir, next episode, digit width, order,
  order-was-missing. Exit 4 = season not found and no `N:Name` to create it; 5 = order value not `feed`/`course`;
  6 = feed season has no episode numbers left. The Python side reports every non-zero exit as "Could not resolve".
- `FITNESS_LIST_SCRIPT` prints one tab-separated line per season: show, number, title, episode count, order —
  plus `<show>\t\t\t0\t` for a show that has no seasons yet, so the picker can still list it.

## 5. Testing

`tests/conftest.py` provides `fake_ssh`, a Python fake for `ssh._execute` that records every call and answers
by rules keyed on the command text (and, for the fitness scripts, on the script content sent over stdin) —
the same discrimination the old bats stub did. `PLAYLIST_ITEM_SCRIPT` is additionally run for real under bash
with a fake `yt-dlp` and `rsync` on `PATH`. `jellyfin_nfo.py` is tested both imported and as a script piped to
`python3 -`.
