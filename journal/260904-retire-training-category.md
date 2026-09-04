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

**Not done.** 39 findings remain, recorded in the report. Worth doing next: a coverage floor and
`uv sync --frozen` (nothing gates coverage today), SSH timeouts, and distinguishing an unreachable
media VM from a missing yt-dlp — currently the former is reported as the latter.
