# 2026-09-04 — Retire `-g`/`training`; fix what an engineering-team pass turned up

**Why.** `-g` filed gym videos flat into `youtube/training/`; `yt -f` (Aug 2026) files them as
episodes of a Jellyfin *Health & Fitness* show with an `.nfo` and a thumbnail. Keeping both left
two plausible homes for the same video, described in near-identical words, one keystroke apart.
The shell history has `yt -g <URL>` and then `yt -f <same URL>` 74 seconds later — that video is
in both trees. Nothing outside interactive use called `-g`.

**What landed.** Nine work units from a full evaluation (`.engineering-team/runs/manual-20260903T171849Z/`).

- **W1 — the remote scripts are now actually tested.** They are where the download, rename,
  staging and NAS transfer happen, and nothing exercised them: `FakeSSH` matches command text and
  returns a canned tuple, so it checks *which* script ran and how args were quoted, and nothing
  about what the script does. Five destructive mutations — including swapping the `NAS_SCRIPT`
  rsync source and destination, which moves the finished library back into staging and deletes it
  from tank — left all 133 tests green. `tests/conftest.py` gained a `run_remote` fixture that
  pipes a script to a real `bash -s -- args…` against a temp tree with the real rsync and a fake
  yt-dlp. All five mutations are caught now. **Python line coverage did not move**, because these
  tests exercise bash, which `coverage` cannot see — which is the finding restated: the number was
  never measuring the risky part.
- **W2 — subtitles never worked.** `--sub-format "srv3/…"` is a preference list and YouTube offers
  srv3 for every auto-translated track, so srv3 won; `--convert-subs srt` then handed it to ffmpeg,
  which has no srv3 demuxer, and yt-dlp exited 1. Now `srt/ttml/vtt/best`. Separately `--sub-langs
  "en.*"` matched `en-en` and `en-de` (yt-dlp names translations `<target>-<source>`), each costing
  a `--sleep-subtitles` pause — that was the HTTP 429. Verified live: before, exit 1 and three
  tracks; after, exit 0, one track, and `ffprobe` shows a `subrip` stream in the mkv.
- **W3 — `yt -f` was writing `.nfo` paths to stdout.** `capture=False` makes the child inherit
  yt's stdout, and the helper prints every sidecar it writes, so `yt -f URL | epm` got `.nfo`
  paths ahead of the video. `FakeSSH` also silently dropped `capture=False` output, so no test
  could see it; it now models the inheritance, which reddened the existing test immediately.
- **W4 — an unknown height silently became "you already have a better copy".** `_height()` mapped
  both `"NAp"` and `"0p"` to `0`, so `new <= old` was always true. **The evaluation's stated
  trigger was wrong** and is corrected in the report: it blamed a *failed info fetch*, but that
  path sets `video_id="unknown"`, so `find_existing` matches nothing and the comparison is never
  reached. Driving all four combinations through `download_single` found the real one.
- **W5 — path traversal.** A show name became a directory with no validation, so `yt -f "../1:X"`
  created a season in the movies-library root, on both NFS and NAS. `safe_show_name()` rejects
  path-significant forms while keeping what the library actually uses (`Mobility & Physio`,
  `Combat Sports`). Guarded on the remote side too, and the NAS path derivation no longer relies
  on `removeprefix`, which is a silent no-op when the prefix is absent.
- **W6 — the two unquoted interpolations.** `video_id` is extractor metadata, and it was spliced
  into a single-quoted shell literal. `ssh.id_glob()` handles find's globbing, `q()` the shell.
- **W7 — playlist leaked a staging dir per archived skip**, forever; and the "keep staging for
  recovery" rule was asserted on only two of the four paths that must honour it. Both unasserted
  mutations are now caught.
- **W8/W9 — the retirement itself**, plus a "Which mode do I use?" section, which is the thing
  whose absence made the two flags confusable.

**Gotchas met.** macOS ships bash 3.2 and openrsync; the scripts need bash ≥ 4 (`${t,,}`) and GNU
rsync (`--info=progress2`), so the harness discovers both and skips cleanly without them — my
first run picked up `/usr/bin/rsync` and failed with a usage dump. My first `fake_bin` fixture put
its `bin/` dir inside `tmp_path`, which `FITNESS_LIST_SCRIPT` then correctly reported as a show.
And an `ffmpeg … | head` check reported success on a command that had failed — the same
exit-code-through-a-pipe defect the evaluation records as F10 in `playlist.py`.

**Corrected in the report.** F4's mechanism (above). F19: the NFS mounts are at
`/mnt/nfs/movies` and `/mnt/nfs/downloads`, *not* `/mnt/nfs` — the obvious guard,
`mountpoint -q /mnt/nfs`, would fail on a healthy system every time. F33: refuted, deno and node
are both installed on the media VM.

## Wrap-up: what review caught that I didn't

Two independent passes ran over the finished branch, because the author of a change is the worst
person to check it. Both found real things, and the pattern is worth recording: **every one of
them was a second-order effect of a fix, not a miss in the original code.**

- **W5 introduced a cookie leak.** `split_target()` gained validation and is called *inside* the
  fitness `Session`, after the cookie is uploaded — so a rejected name raised past every cleanup
  path, leaving `$tmpdir` and a live `cookies.txt` on the media VM. The deeper error was
  validating the wrong thing: a name that came back from the *remote listing* is an existing
  directory, not user input, so a real show called `-Rehab` would be listed, offered by the
  picker, and then rejected. `split_target()` is pure again; `safe_show_name()` is applied only
  where a user supplies a name.
- **The retirement notice pre-empted `--update`**, so `yt --update -g` refused to update.
- **`season_order()` silently dropped an inline `:feed`/`:course`.**
- **`item.cleanup()` on an archived skip cost an ssh round trip per item** — on a re-run of a
  200-item playlist, 200 connections to delete 200 empty directories. The script already knows it
  is an archived skip and already `rmdir`s its tmp dir, so it drops its staging dir there too.
- **The docs audit found twelve items**, three of them created by W9 — the commit whose whole
  purpose was doc accuracy. The sharpest: W5 gave `exit 4` a second meaning and §4 still
  documented only one. `README` still said 133 tests. And my "roughly eight ad-hoc `ssh()` call
  sites" was a guess; the real count is eleven, which the auditor got by counting.

`id_glob()`'s escaping — the thing I was least sure of — was checked against real `find(1)`
fnmatch behaviour and holds: the backslashes are for fnmatch, `shlex.quote` then delivers them
byte-for-byte, and the two layers do not stack.

**Grades.** Confirmed by execution: the subtitle fix (live yt-dlp A/B, `ffprobe` shows a `subrip`
stream), the traversal fix (sandbox reproduction now exits 4), all five W1 mutations and both W8
mutations caught, and the `-g` interception. Strongly supported: the staging-leak accounting.
Suspected and *unsettled*: whether the mkv survived the old subtitle error in a non-429 run —
irrelevant now that the flags are fixed, but never proven either way.

## What is deliberately not done

- **39 of the 51 findings.** They are in the evaluation report, not lost. The ones worth doing
  next: a coverage floor and `uv sync --frozen` (nothing gates coverage today, so 96% could fall
  to 40% and CI stays green); SSH timeouts (`yt` hangs forever on a hung media VM); and
  distinguishing an unreachable media VM from a missing yt-dlp — the former is currently reported
  as the latter, sending you to `yt --update`, which fails the same way.
- **A mount guard.** The live check corrected the fix before it was written: the NFS mounts are
  `/mnt/nfs/movies` and `/mnt/nfs/downloads`, *not* `/mnt/nfs`, so the obvious
  `mountpoint -q /mnt/nfs` would fail on a healthy system every time.
- **Nothing on the NAS was moved.** Files already in `youtube/training/` stay put; the docs say
  the directory is legacy. Migrating them into fitness shows would be its own job — those files
  have no `info.json`, so the `.nfo` and thumbnail would have to be synthesised.
- **`ssh.lines()` is dead code** (no caller, no test) and was left alone: it is on the deferred
  list, and deleting it was not in this plan's scope.
- **The three modes still carry near-duplicate download/stage/transfer logic**, and the yt-dlp
  flag block is copied across eight sites. That is the right long-term fix and it is a rewrite,
  not a repair.
