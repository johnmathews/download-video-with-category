**Status:** point-in-time evaluation, 2026-09-03/04, at commit `559832d`. **Not a living document** — do not
edit it to match later code. 12 of its 51 findings were fixed in PRs #2 and #3; the rest are open and are the
reason this file is kept. Fixed: F1-F9 (PR #2), F14, F21, F22, F26, F35, F41, F44, F47 (PR #2), F16, F17, F18
(PR #3). Regraded after the fact: F4 (mechanism corrected), F13 (settled — unreachable as configured), F19
(remediation corrected), F33 (refuted). The index is ordered by the severity each finding had when written, so
the regraded rows are no longer in strict order.

See [journal/260904-retire-training-category.md](../../journal/260904-retire-training-category.md) for what was
done about it.

---

# Evaluation report — `yt` (download-video)

> Purpose
>
> A full evaluation of the `yt` CLI at commit `559832d` (branch `main`), run on
> 2026-09-03/04 as Phase 1 of an engineering-team cycle. The user's presenting
> request was narrow — retire the `-g` / `training` category now that `-f`
> fitness mode supersedes it — and agreed to widen it to a full repo pass with
> that retirement as one work unit. Scope: structure and code quality, tests and
> reliability, security and robustness, deployment/CI, and documentation. Read
> section 1 and section 2; everything below section 3 is evidence and reference.

## 1. Executive summary

`yt` is a well-built personal CLI with an unusually honest CI pipeline, zero
runtime dependencies, and documentation whose factual claims mostly survive
checking — two of the highest-risk doc claims (the remote-script stdout
contracts in `architecture.md` §4, and the README category table) were verified
correct. The 133-test suite passes at 96% line coverage.

That coverage number is misleading, and it is the headline result. **The remote
bash scripts in `yt/remote_scripts.py` are where all the real work happens, and
they are almost entirely unexercised**: five destructive mutations — including
swapping the NAS rsync source and destination, which would move the finished
library back into staging and delete it from tank — leave all 133 tests green
(F1). Separately, a live test proved the subtitle configuration has never
worked as intended: `--sub-format "srv3/…"` with `--convert-subs srt` fails,
because ffmpeg cannot read srv3 (F2).

Fix first: F1 (a real-bash test harness — the machinery already exists in
`tests/test_playlist.py`), then F2, F3 (`yt -f` writes `.nfo` paths to stdout,
breaking the project's one hard invariant), and F4 (a failed info fetch is
silently reported as "already have a better copy", exit 0). The `-g` retirement
that prompted this run is real and worth doing (F9), but it is the smallest
item on this list.

## 2. Findings index

| ID | Severity | Grade | Finding | Location |
| --- | --- | --- | --- | --- |
| F1 | Critical | [VERIFIED] | Remote bash scripts are untested; 5 destructive mutations incl. a library-destroying rsync swap leave all 133 tests green | `yt/remote_scripts.py:10-359` |
| F2 | High | [VERIFIED] | Subtitles are never embedded as configured — `srv3` + `--convert-subs srt` fails and yt-dlp exits 1 | `yt/remote_scripts.py:53,140,328` |
| F3 | High | [VERIFIED] | `yt -f` writes `.nfo` paths to stdout, breaking the "stdout is final paths only" invariant | `yt/fitness.py:328-333` |
| F4 | High | [VERIFIED] | An *unknown* video height silently becomes "existing file is better" — skips the download and exits 0 (the reported "failed info fetch" trigger was refuted; corrected by W4) | `yt/single.py:37-39,95-101` |
| F5 | High | [VERIFIED] | Path traversal: an unvalidated show name writes outside the fitness tree | `yt/remote_scripts.py:232`, `yt/fitness.py:113,180` |
| F6 | High | [VERIFIED] | Remote-derived `video_id` is interpolated unquoted into a remote shell command | `yt/single.py:44`, `yt/fitness.py:206` |
| F7 | High | [VERIFIED] | Playlist mode leaks one empty SSD staging dir per archived-skip item, permanently | `yt/playlist.py:110-113` |
| F8 | High | [VERIFIED] | The "keep staging for manual recovery" invariant is asserted on only 2 of the 4 paths that must honour it | `yt/fitness.py:334-336`, `yt/playlist.py:119-121` |
| F9 | High | [SUPPORTED] | Nothing documents when to use `-g training` vs `-f` fitness; the deprecated path is the most prominent example in every doc | `README.md:36,50,52,63`, `yt/cli.py:59,61,79` |
| F10 | Medium | [SUPPORTED] | A truncated playlist listing is indistinguishable from a short playlist; the run reports success | `yt/playlist.py:29-36` |
| F11 | Medium | [SUPPORTED] | `--season-order`, documented as "show or set", creates show and season directories as a side effect | `yt/fitness.py:356-370` |
| F12 | Medium | [VERIFIED] | Ctrl-C mid-playlist leaves the uploaded YouTube cookie on the media VM permanently | `yt/session.py:65-69` |
| F13 | Low | [VERIFIED] | The Jellyfin scan endpoint blocks against a 10s timeout — but the code path is unreachable as configured: `JELLYFIN_URL`/`JELLYFIN_API_KEY` are unset, so the scan is never requested (settled 2026-09-04) | `yt/fitness.py:219-225` |
| F14 | Medium | [VERIFIED] | `--sub-langs "en.*"` matches auto-translated tracks, not English-only, and triggers HTTP 429 | `yt/remote_scripts.py:48,135,328` |
| F15 | Medium | [VERIFIED] | The yt-dlp flag block is hardcoded at 8 sites with no shared constant; a change to one is silently not applied to the others | `yt/remote_scripts.py:42,66,126,155,313` +3 |
| F16 | Medium | [VERIFIED] | Coverage is measured but not gated, and CI runs `uv sync` rather than `--frozen` | `.github/workflows/test.yml:15,17` |
| F17 | Medium | [VERIFIED] | No SSH or subprocess timeout anywhere: `yt` hangs indefinitely on a hung media VM | `yt/ssh.py:28-31,44` |
| F18 | Medium | [VERIFIED] | An unreachable media VM is reported as "yt-dlp not found — install it with `yt --update`" | `yt/cookies.py:32-36` |
| F19 | Medium | [SUSPECTED] | Nothing checks the NFS mounts; a stale mount would write the library to the media VM's local disk (mounts are live today, and are one level deeper than the obvious guard) | `yt/remote_scripts.py:260-266`, `yt/playlist.py:75` |
| F20 | Medium | [VERIFIED] | `*.json` and `*info.json` double-list the same file, making rsync exit 23 — after which the caller deletes the good staged files | `yt/remote_scripts.py:83,186` |
| F21 | Medium | [SUPPORTED] | `architecture.md` §2 claims a stage-2 failure always prints the manual recovery command; only single mode does | `docs/architecture.md:32-33` |
| F22 | Medium | [SUPPORTED] | `architecture.md` §4 states quoting is "a solved problem in exactly one function", which F6 contradicts | `docs/architecture.md:56-57` |
| F23 | Medium | [VERIFIED] | The fake-SSH harness routes on command substrings and a bash comment: brittle to cosmetic edits, blind to semantic ones | `tests/conftest.py:37-49` |
| F24 | Medium | [VERIFIED] | The stdout contract is enforced in single and fitness tests but not playlist; a stray `print()` there ships silently | `tests/test_playlist.py:59,71` |
| F25 | Medium | [SUPPORTED] | No living doc carries a status or verification stamp; the one known caveat is buried in an unlinked journal entry | `README.md:1-3`, `docs/architecture.md:1-3` |
| F26 | Medium | [VERIFIED] | `journal/` is linked only from the agent-facing `CLAUDE.md`, and the last three commits left no entry | `journal/`, `CLAUDE.md:49-51` |
| F27 | Medium | [SUPPORTED] | The setup path omits the remote-side contract: non-interactive SSH, and the four NFS mounts the tool hardcodes | `README.md:18-30`, `yt/cli.py:81-84` |
| F28 | Medium | [SUPPORTED] | "Old file will be replaced" — nothing deletes the old file; replacement is incidental on the filename matching | `yt/single.py:102-104` |
| F29 | Medium | [SUPPORTED] | The NFS→NAS path pairing is rebuilt three times by three techniques; fitness uses a `removeprefix` that fails open | `yt/fitness.py:339-340` |
| F30 | Medium | [VERIFIED] | Nothing exercises an end-to-end path, though the `$YT_SSH` seam that would allow it already exists | `yt/config.py:47-49` |
| F31 | Medium | [SUPPORTED] | The same destination is given two absolute paths across the docs with no explanation that they are one tree from two hosts | `README.md:79,142` vs `yt/cli.py:87-89` |
| F32 | Medium | [SUPPORTED] | `-f bestvideo+bestaudio` has no fallback and errors on progressive-only sources | `yt/remote_scripts.py:55,71,142,164,322` |
| F33 | Low | [SUPPORTED] | `--remote-components ejs:github` is redundant on the installed binary and adds a GitHub fetch per extraction (the JS-runtime concern was checked and refuted) | `yt/remote_scripts.py:42` +7 |
| F34 | Low | [SUPPORTED] | The 38 uncovered statements are almost entirely the failure paths that only run during an incident | `yt/playlist.py:76-78`, `yt/fitness.py:265-268` |
| F35 | Low | [SUPPORTED] | The docs never say how a category download reaches Jellyfin, though both other modes document it | `README.md:32-55` |
| F36 | Low | [SUPPORTED] | Fitness stages `"$tmpdir"/*` while the other two modes stage a whitelist — correct today, for an unrecorded reason | `yt/remote_scripts.py:352` vs `:83,186` |
| F37 | Low | [VERIFIED] | `ssh.lines()` is dead code — no caller, no test, absent from the architecture doc's API list | `yt/ssh.py:67-69` |
| F38 | Low | [SUPPORTED] | `yt --update` pins the stable channel, which upstream calls "often stale"; nightly is the recommended channel | `yt/remote_scripts.py:361-368` |
| F39 | Low | [SUPPORTED] | `yt --update` installs an unverified binary as root — no checksum, no signature | `yt/remote_scripts.py:363-367` |
| F40 | Low | [SUPPORTED] | `_xml()` does not escape `"`, and the escaped value is used inside an XML attribute | `yt/jellyfin_nfo.py:122-123,155` |
| F41 | Low | [VERIFIED] | `CLAUDE.md` says the README category table "derives from" `CATEGORIES`, then says to update it by hand | `CLAUDE.md:30-33` |
| F42 | Low | [SUPPORTED] | `--help`'s REQUIREMENTS omits the `nas` host and `ffprobe`, both of which every download needs | `yt/cli.py:81-84` |
| F43 | Low | [VERIFIED] | `--help` writes to stderr, so `yt --help \| less` silently produces nothing; no doc says so | `yt/cli.py:138,142` |
| F44 | Low | [SUPPORTED] | `architecture.md` does not link the archived design docs it superseded | `docs/architecture.md` |
| F45 | Low | [SUPPORTED] | `epm` justifies the project's most invasive design constraint and is never explained | `CLAUDE.md:17`, `README.md:63` |
| F46 | Low | [SUPPORTED] | The playlist slug fallback silently suggests a directory literally named `playlist` | `yt/playlist.py:66` |
| F47 | Low | [SUPPORTED] | README's duplicate-detection paragraph describes single mode only but reads as global | `README.md:15-16` |
| F48 | Low | [SUSPECTED] | A multi-video fitness download would mismatch filename and nfo episode numbers, and count the wrong way for feed seasons | `yt/remote_scripts.py:343-350` |
| F49 | Low | [SUPPORTED] | `playlist._confirm_slug` accepts the suggestion on EOF; the equivalent fitness prompt refuses | `yt/playlist.py:42-43` |
| F50 | Low | [SUPPORTED] | Port artefacts: `Session` is a two-phase object whose `__exit__` raises, plus several transliterated shell idioms | `yt/session.py:32-43,62-69` |
| F51 | Low | [SUPPORTED] | The episode NFO carries three inert fields and omits two useful ones (`genre`, `dateadded`) | `yt/jellyfin_nfo.py:137-157` |

## 3. Findings in detail

### F1 Remote bash scripts are untested

- **Severity:** Critical — a wrong `rsync` in `NAS_SCRIPT` destroys the finished
  library on tank and the suite reports success. This is silent wrongness in the
  one component that touches irreplaceable data.
- **Grade:** [VERIFIED] — five semantic mutations applied, suite re-run, quoted below
- **Location:** `yt/remote_scripts.py:10-26`, `:31-106`, `:200-219`, `:229-299`, `:305-359`
- **Disconfirming check:** If the scripts *were* covered, at least one mutation
  would go red. A control mutation on the one script that *is* executed
  (`PLAYLIST_ITEM_SCRIPT`, collapsing its `exit 0`/`exit 3` discrimination)
  correctly failed `test_item_script_real_failure_exits_3` — so the harness can
  detect this class of change where it actually runs the script. It does not run
  the other five.

`tests/conftest.py:37-49` matches rules by substring of the command line and,
for fitness, of the script text on stdin, then returns a canned tuple. That
verifies which script Python chose and how it quoted the arguments. It verifies
nothing about what the script does. Only `PLAYLIST_ITEM_SCRIPT` is ever piped to
a real `bash`.

Uncovered as a result: every glob, the retry-without-subtitles fallback, sidecar
cleanup, the rename loop, `10#` season parsing, the feed/course numbering
arithmetic, the `exit 4/5/6` codes, and the entire NAS transfer.

```console
$ # mutations applied: NAS rsync src/dest swapped; --cookies dropped from single;
$ # next=$((max+1)) -> next=$max; SnnEnn printf broken; list columns transposed
$ uv run python -m pytest -q
133 passed in 0.22s

$ # control: same exercise on the one script that IS executed for real
$ uv run python -m pytest -q
1 failed, 16 passed
FAILED tests/test_playlist.py::test_item_script_real_failure_exits_3
```

### F2 Subtitles are never embedded as configured

- **Severity:** High — every download since this flag combination was introduced
  has been silently missing the subtitles the config asks for. Bounded (the video
  itself is fine) and loud only on stderr.
- **Grade:** [VERIFIED] — reproduced against live yt-dlp 2026.08.19 on the URL the
  project's own `--help` uses as its example
- **Location:** `yt/remote_scripts.py:53`, `:140`, `:328`
- **Disconfirming check:** If the combination worked, the convertor would emit
  `.srt` and exit 0. It does not. I also tested the underlying mechanism
  separately — ffmpeg cannot open an srv3 file at all (exit 183, "Invalid data
  found"), which is the reason rather than a coincidence of this one video.

`--sub-format "srv3/ttml/vtt/best"` is a *preference list*, so `srv3` is chosen
whenever YouTube offers it — the normal case. `--convert-subs srt` then hands it
to ffmpeg, which has no srv3 demuxer.

```console
$ yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs "en.*" \
    --convert-subs srt --sub-format "srv3/ttml/vtt/best" "https://youtu.be/C4TVr2NtEg8"
[info] C4TVr2NtEg8: Downloading subtitles: en-orig, en
[SubtitlesConvertor] Converting subtitles
ERROR: Preprocessing: Error opening input files: Invalid data found when processing input
ERROR: Preprocessing: Error opening input files: Invalid data found when processing input
EXIT=1

$ ffmpeg -hide_banner -loglevel error -y -i t.srv3 o1.srt
exit=183
[in#0] Error opening input: Invalid data found when processing input
```

**What is not settled:** whether the mkv survives this error in a full run, i.e.
whether the script's `video_files` check fires the retry (`remote_scripts.py:63-77`)
or keeps a video with no subtitle track. My second test — the real flag set on a
19-second video — was aborted by an HTTP 429 before the video stage, and I was
rate-limited out of retrying. Either branch loses the subtitles; only the stderr
message differs. Settle it with one real `yt -y <url>` run: watch for
`⚠️ Subtitle error may have aborted download` and `ffprobe` the result for a
subtitle stream.

The fix is `--sub-format "srt/ttml/vtt/best"` — `srt` makes `--convert-subs` a
no-op, and `ttml` takes yt-dlp's pure-Python `dfxp2srt()` path rather than
ffmpeg. Three edit sites, or one if F15 is fixed first.

### F3 `yt -f` writes `.nfo` paths to stdout

- **Severity:** High — breaks the single invariant the whole codebase is shaped
  around. `yt -f URL | epm` receives `.nfo` paths as if they were videos, ahead
  of the real path.
- **Grade:** [VERIFIED] — reproduced through a stub `$YT_SSH`; mechanism confirmed
  by reading `ssh.py:25`
- **Location:** `yt/fitness.py:328-333`, via `yt/ssh.py:25` to `yt/jellyfin_nfo.py:200`
- **Disconfirming check:** If `capture=False` did not inherit stdout, the paths
  would not appear. `ssh.py:25` is `stdout = subprocess.PIPE if capture else None`
  — `None` means inherit. `jellyfin_nfo.main()` unconditionally `print(p)`s every
  sidecar it writes.

`CLAUDE.md:17`, `docs/architecture.md:21` and `ui.py:1` all state that stdout
carries final file paths only. The `FakeSSH` harness fabricates a
`CompletedProcess` and never inherits a real stdout, which is why 133 passing
tests do not catch it. The fix is one word — `capture=True` — plus routing the
captured output to `info()`.

Running the helper directly, with stderr discarded so only stdout is shown:

```console
$ D=$(mktemp -d); touch "$D/Show S01E05 - clip-[abc123].mkv"
$ uv run python yt/jellyfin_nfo.py "$D" "Show" 1 5 2>/dev/null
/var/folders/n7/m4mv7nhx6m39gljs3zpmq3nw0000gn/T/tmp.wR0XJL9Unp/Show S01E05 - clip-[abc123].nfo
exit=0
```

### F4 An unknown video height silently becomes "existing file is better"

- **Severity:** High — silent wrongness: `yt` reports success, emits the old
  path, and does not download. A scripted caller sees a clean exit 0.
- **Grade:** [VERIFIED] — executed during W4; both the real trigger and the
  refutation of the reported one are quoted below
- **Location:** `yt/single.py:37-39`, `:95-101`
- **Disconfirming check:** **this is the finding the check corrected.** As
  originally reported, the trigger was "the info fetch fails, so
  `fetch_video_info` returns its `("unknown", …, "0p", "0")` sentinel". That
  mechanism is **wrong**: when the fetch fails, `video_id` becomes `"unknown"`,
  so `find_existing` searches for `*[unknown]*`, matches nothing, and the
  comparison is never reached. Driving all four combinations through
  `download_single` with a faithful id-dependent `find`:

```console
A. whole --print fails, existing file present    rc=0  downloaded=True   <- NOT the bug
B. height is 'NA', existing file present         rc=0  downloaded=False  <- the bug
C. height fine, existing lower quality           rc=0  downloaded=True
D. height fine, existing higher quality          rc=0  downloaded=False
```

The real trigger is narrower: yt-dlp returns id and title fine but prints `NA`
for `%(height)s` (audio-only formats, some live streams, some extractors), so
`new_quality` is `"NAp"`, `_height` mapped it to `0`, and `0 <= n` is true for
every `n` — so the skip branch always won. `yt` then printed "existing file has
equal or better quality" having never learned the new quality, emitted the old
path and exited 0.

The mirror case is real too and was previously described as safe: when ffprobe
fails, `existing_quality` returns `"0p"`, and the code proceeded to download —
producing a duplicate rather than a wrong skip. W4 refuses both.

An earlier probe of mine reported scenario A as buggy; that probe's fake `find`
returned the existing file regardless of which id was searched for, which is not
what `find -name '*[id]*'` does. Recorded because it is the same class of error
as the finding itself — a check that could not distinguish the two cases.

### F5 Path traversal via an unvalidated show name

- **Severity:** High — a typo silently files an episode outside the Jellyfin
  fitness library, into the movies-library root, on both the NFS and NAS sides.
  Nothing is overwritten or deleted, so it is recoverable but easy to miss.
- **Grade:** [VERIFIED] — `FITNESS_RESOLVE_SCRIPT` executed against a sandbox tree
- **Location:** `yt/remote_scripts.py:232`; reachable from `yt/fitness.py:180` and `:113`
- **Disconfirming check:** if `split_target` or the resolve script normalised the
  path, `..` would be rejected. I read both: `split_target` does a bare
  `target.split("/", 1)` with no validation, and the script does
  `show_dir="$base/$show"`. `add_to_show` *does* guard the no-slash case
  (`fitness.py:270`), so that specific concern is closed — but not this one.

```console
$ /bin/bash resolve.sh "$SB/movies/youtube/fitness" ".." "1:Escaped" ""
🆕 Created .../movies/youtube/fitness/../Season 01 ("Escaped")
$ find $SB
/movies/youtube/Season 01/season.nfo      <-- outside fitness/
```

`fitness.py:339`'s `removeprefix` then carries the unnormalised `../Season 01`
into `nas_season_dir`, so the NAS copy lands outside the tree too. Bounded to one
level (a show name cannot contain `/`). Contrast `playlist.py:15-17`, which
sanitises its directory name properly — fitness does no validation at all.

### F6 Unquoted `video_id` interpolated into a remote shell command

- **Severity:** High — the one place the project's own "never interpolate" rule
  is broken. Not exploitable by a third party today, but it bypasses the guard
  rail (`ssh.q`) the codebase was explicitly built around.
- **Grade:** [VERIFIED] — command string reconstructed and quoted below; I also
  independently read both call sites
- **Location:** `yt/single.py:44`, `yt/fitness.py:206`
- **Disconfirming check:** if `q()` covered it, the id would appear inside a
  `'…'`-wrapped token. `final_dir` does; `video_id` does not — it sits inside a
  single-quoted glob, so an id containing `'` closes the literal.

```console
find /mnt/nfs/movies/youtube/training -type f -name '*\[abc'; rm -rf /tmp/x; #\]*' 2>/dev/null | head -1
```

`video_id` is `parts[0]` of yt-dlp's `--print '%(id)s'` — extractor-controlled
metadata, not user input, and `yt` explicitly proceeds on any URL
(`single.py:17-21`). YouTube ids are `[A-Za-z0-9_-]{11}`, so this is inert on the
sites actually used. Realistic consequence today is not a remote attacker; it is
that the codebase's one safety invariant has two holes in it and no test would
notice a third being added. Fix: `q(f"*[{video_id}]*")`, or pass it as a
`run_script` positional.

### F7 Playlist mode leaks a staging directory per archived skip

- **Severity:** High — re-running a fully-archived 200-item playlist (the normal
  way to top up a library) leaves 200 new empty directories on the SSD every
  time, and destroys the operational signal that "something in yt-staging" means
  "something needs manual recovery".
- **Grade:** [VERIFIED] — probe recording every remote command issued for a
  3-item all-skips playlist
- **Location:** `yt/playlist.py:110-113`; dir created at `yt/remote_scripts.py:122`
- **Disconfirming check:** the obvious refutation is that `with item:` cleans up
  on exit. It does not — I read `Session.__exit__` (`session.py:65-69`), which
  acts **only** on `KeyboardInterrupt`. The skip branch `continue`s past both
  `item.cleanup()` and `nas_transfer()`, and the class docstring says the NAS
  script is what removes the staging dir.

```console
rm -rf calls issued: ['rm -rf /tmp/yt.stub1 2>/dev/null || true']   # cookie session only
# /mnt/nfs/downloads/yt-staging/yt.stub2..4 never removed
```

`tests/test_playlist.py:82-89` covers exactly this scenario and asserts only the
`nas` call count.

### F8 The staging-recovery invariant is asserted on 2 of 4 paths

- **Severity:** High — a refactor that "tidies up" either unasserted failure path
  deletes a fully downloaded, fully staged episode, and the suite stays green.
- **Grade:** [VERIFIED] — both unenforced paths mutated to destroy the recovery
  data; suite re-run
- **Location:** enforced at `tests/test_single.py:104`, `tests/test_fitness.py:215`;
  unenforced at `yt/fitness.py:334-336`, `yt/playlist.py:119-121`
- **Disconfirming check:** if the invariant were covered, adding a `cleanup()`
  call to those paths would fail a test. It did not.

```console
$ # added session.cleanup() after the nfo-failure message in yt/fitness.py
$ # added item.cleanup()  after the playlist NAS-failure message
$ uv run python -m pytest -q
133 passed in 0.21s
```

`CLAUDE.md:26-28` states the invariant explicitly. `tests/test_fitness.py:218`
asserts the message and that NAS was not called, but never that staging survived.

### F9 Nothing documents when to use `-g` vs `-f`

- **Severity:** High — a stated quality requirement of the tool (file videos
  *correctly*) that nothing supports, and it has already produced a real misfile.
- **Grade:** [SUPPORTED] — read every doc section; no "which mode" guidance exists
- **Location:** `README.md:36,50,52,63`, `yt/cli.py:59,61,79`, `docs/architecture.md:48`
- **Disconfirming check:** a "which mode do I want" section anywhere would refute
  it. `grep` across `README.md`, the `HELP` string and `architecture.md` finds
  none; the two destinations are described 40 lines apart in synonymous
  vocabulary ("Training and gym/workout videos" vs "Health & Fitness").

The evidence this is not hypothetical is in the user's own shell history — `yt -g`
on a URL, then `yt -f` on the *same URL* 74 seconds later:

```console
1087:: 1788448909:0;yt -g https://youtu.be/HRv3qwFWYlY?si=...
1088:: 1788448983:0;yt -f https://youtu.be/HRv3qwFWYlY?si=...
```

Compounding it: `-g`/`training` is the canonical example in the README Usage
block, the `--help` EXAMPLES, `architecture.md` and `CLAUDE.md` — so the mode
being retired is the most prominently documented one in the project.

### F10 A truncated playlist listing reports success

- **Severity:** Medium — the user is told the run succeeded when it downloaded a
  prefix of the playlist. Recoverable (the `--download-archive` makes a re-run
  cheap) but nothing signals that a re-run is needed.
- **Grade:** [SUPPORTED] — read `yt/playlist.py:29-36`; not executed
- **Location:** `yt/playlist.py:29-36`
- **Disconfirming check:** if the `returncode` guard at `:36` worked, a yt-dlp
  failure would be caught. The command ends `2>/dev/null | wc -l`, so the remote
  shell's status is `wc`'s — always 0. The guard is unreachable. What keeps this
  honest today is only the empty-output message at `:81-84`.

This is the same class as the pipe-masks-exit-code trap; I hit it myself during
this evaluation and had to redo an ffmpeg check for the same reason.

### F11 `--season-order` creates directories as a side effect

- **Severity:** Medium — `yt --season-order "NewShow/7:Rowing"`, a typo away from
  a legitimate query, silently creates `fitness/NewShow/Season 07/` with a
  `tvshow.nfo` and `season.nfo` in the live Jellyfin library, then prints a
  normal-looking status line.
- **Grade:** [SUPPORTED] — read `yt/fitness.py:356-370` and `remote_scripts.py:253-268`
- **Location:** `yt/fitness.py:356-370`
- **Disconfirming check:** a read-only path for the query case would refute it.
  `season_order()` calls the same `resolve()` as the download path, and the
  script's `N:Name` branch runs `mkdir -p` unconditionally. To settle by
  execution, run it against a sandbox tree as F5 was.

The help text (`cli.py:53-54`) says only "Show or set a season's order".

### F12 Ctrl-C mid-playlist leaves the cookie on the media VM

- **Severity:** Medium — credential *residue*, not exposure: mode 0600 under
  `umask 077` on a host the user owns, in `/tmp`. But `session.py:3-5` documents
  the opposite behaviour, and every interrupted playlist adds another one.
- **Grade:** [VERIFIED] — nested-session reproduction with `ssh._execute` stubbed
- **Location:** `yt/session.py:65-69`, exercised by `yt/playlist.py:59` + `:101`
- **Disconfirming check:** if the outer session cleaned up, an `rm -rf` covering
  the outer tmpdir would appear. It does not.

```console
outer cookie file on media VM: /tmp/yt.pl.STUB1/cookies.txt
SystemExit code: 130
remote commands: mktemp -d /tmp/yt.pl.XXXXXX; umask 077 && cat > /tmp/yt.pl.STUB1/cookies.txt;
                 mktemp -d /tmp/yt.XXXXXX; rm -rf /tmp/yt.STUB2 ... || true
any rm -rf covering the outer cookie dir?: False
```

The inner `__exit__` converts the interrupt to `SystemExit(130)`; the outer one
tests `isinstance(exc, KeyboardInterrupt)`, matches nothing, and returns. Single
and fitness modes are unaffected — they use one un-nested session. Fix: catch
`SystemExit` too, or use `finally`.

### F13 The Jellyfin scan endpoint blocks; `timeout=10` likely reports a false failure

- **Severity:** Low — reduced from Medium. The defect is real in the code but the
  branch is never taken on this installation.
- **Grade:** [VERIFIED] — settled 2026-09-04 by checking the configuration rather
  than the server
- **Location:** `yt/fitness.py:219-225`
- **Disconfirming check:** the planned check was a live `yt -f` run against the
  Jellyfin server. A cheaper one settled it first: the blocking call is guarded by
  `jellyfin_credentials()`, which returns `None` unless **both** `JELLYFIN_URL` and
  `JELLYFIN_API_KEY` are set. Neither is set in the user's environment or anywhere
  in their shell config, so `request_jellyfin_scan()` takes its early return and
  prints "Jellyfin picks it up on the next scheduled scan". The 10-second timeout
  has never been reached.

```console
$ echo "JELLYFIN_URL: ${JELLYFIN_URL:-unset}  JELLYFIN_API_KEY: ${JELLYFIN_API_KEY:-unset}"
JELLYFIN_URL: unset  JELLYFIN_API_KEY: unset
$ grep -l JELLYFIN_URL ~/.zshrc ~/.zshenv ~/.zprofile
(no matches)
```

It stays a latent defect for anyone who does set them, so it is recorded rather
than deleted — but it warrants no code change here.

The endpoint and auth scheme are *correct* and current: `POST /Library/Refresh`
with `Authorization: MediaBrowser Token="…"` is the recommended scheme and
survives the 12.0 `EnableLegacyAuthorization` change (verified against
`https://repo.jellyfin.org/files/openapi/stable/jellyfin-openapi-10.11.11.json`
and `https://api.jellyfin.org/openapi/jellyfin-openapi-stable.json`). The concern
is that `LibraryController` `await`s `ValidateMediaLibrary(...)`, i.e. blocks for
the whole scan, against a 10-second client timeout. Better fits if confirmed:
`POST /Library/Media/Updated` (returns immediately, no elevation) or
`POST /Items/{libraryId}/Refresh` (queued).

### F14 `--sub-langs "en.*"` matches auto-translated tracks and triggers 429

- **Severity:** Medium — more subtitle tracks fetched than intended, each with
  `--sleep-subtitles 1`, ending in rate limiting that fails the whole yt-dlp run.
- **Grade:** [VERIFIED] — observed live during this evaluation
- **Location:** `yt/remote_scripts.py:48`, `:135`, `:328`
- **Disconfirming check:** if the glob were English-only as intended, only `en`
  and `en-*` regional variants would be listed. `en-de` is not a regional English
  variant.

```console
[info] jNQXAC9IVRw: Downloading subtitles: en, en-en, en-de
[download] Sleeping 1.00 seconds ...
ERROR: Unable to download video subtitles for 'en-de': HTTP Error 429: Too Many Requests
```

`journal/260506-jellyfin-thumbnail-and-subs.md` records the intent explicitly —
"English-only… the glob still catches `en`, `en-US`, `en-GB`, and `en-orig`" —
so this is a divergence from a documented decision, not an unconsidered default.

### F15 The yt-dlp flag block is duplicated across 8 sites

- **Severity:** Medium — this is the mechanism by which F2, F14, F32 and F33 each
  become a multi-site edit, and by which a partial fix silently leaves one mode
  on the old behaviour.
- **Grade:** [VERIFIED] — grep counts quoted below
- **Location:** `yt/remote_scripts.py:42,66,126,155,313`; `yt/single.py:28`;
  `yt/playlist.py:23,32`; `yt/fitness.py:194`
- **Disconfirming check:** a shared constant would refute it. There is none —
  each of the three modes carries a full copy, and each *also* carries a second
  copy inside its own retry-without-subtitles fallback.

```console
$ grep -rn "remote-components" --include='*.py' . | wc -l
9
$ grep -c 'bestvideo+bestaudio' yt/remote_scripts.py
5
$ grep -n 'sub-format' yt/remote_scripts.py
53: 140: 328:
```

### F16 Coverage is measured but not gated; CI resolves rather than freezing

- **Severity:** Medium — a stated quality signal with no check behind it.
  Coverage could fall from 96% to 40% and CI stays green.
- **Grade:** [VERIFIED] — grep returns nothing; `uv lock --check` confirms the
  lock is *currently* clean, which is not the same as gated
- **Location:** `.github/workflows/test.yml:15`, `:17`
- **Disconfirming check:** a `fail_under` in `pyproject.toml` or `--cov-fail-under`
  in the workflow would refute it.

```console
$ grep -rn "fail_under" pyproject.toml .github/workflows/test.yml
$ echo $?
1
```

Credit where due: everything else in this pipeline is honest — four separate
`run:` steps, no pipes, no `continue-on-error`, no `|| true`, each able to go
red. The two gaps are `--cov-fail-under` and `uv sync --frozen`.

### F17 No SSH or subprocess timeout anywhere

- **Severity:** Medium — a VM that freezes mid-download hangs `yt` forever with
  no output, which is exactly what a long download invites.
- **Grade:** [VERIFIED] — grep over `yt/ssh.py` and the user's `~/.ssh/config`
- **Location:** `yt/ssh.py:44`, `:28-31`
- **Disconfirming check:** a `ConnectTimeout`/`ServerAliveInterval` in either the
  argv or `~/.ssh/config` would refute it. Neither has one, and no
  `subprocess.run` call passes `timeout=`.

`BatchMode=yes` is correct and covers the host-key question. Two `-o` flags fix
this.

```console
$ grep -nE "BatchMode|ConnectTimeout|ServerAlive|timeout=" yt/ssh.py
43:    """Run `command` on `host` with BatchMode. stderr is inherited so remote progress reaches the terminal."""
44:    argv = [ssh_binary(), "-o", "BatchMode=yes"]
```

`BatchMode` is the only `-o` present, and no `subprocess.run` call passes
`timeout=`.

### F18 An unreachable VM is reported as "yt-dlp not found"

- **Severity:** Medium — this is the *only* remote preflight in the codebase, so
  it is the first thing a user sees when the VM is down, and it sends them to
  `yt --update`, which fails the same way.
- **Grade:** [VERIFIED] — reproduced with a stub `$YT_SSH` returning 255
- **Location:** `yt/cookies.py:32-36`
- **Disconfirming check:** distinguishing 127 from 255 would refute it. The code
  tests only `returncode != 0`.

```console
$ YT_SSH=$SB/fakessh yt -g "https://youtu.be/abc"
❌ yt-dlp not found on media VM
   Install it with: yt --update
exit code: 1
```

### F19 Nothing checks that `/mnt/nfs` is mounted

- **Severity:** Medium — if the mount is down, `mkdir -p` creates the library
  tree on the media VM's local root disk under the mountpoint, invisible once the
  mount returns; `archive.txt` written there is lost, so a re-run re-downloads
  the whole playlist.
- **Grade:** [SUSPECTED] — inferred from the absence of any check; the failure
  itself was not observed
- **Location:** `yt/remote_scripts.py:260-266`, `yt/playlist.py:75`
- **Disconfirming check:** a `mountpoint -q` guard anywhere in the code would
  refute the premise. `grep -rn "mountpoint|/proc/mounts|findmnt" yt/` returns
  nothing, and the only remote preflight is `command -v yt-dlp`. I then checked
  the live host, which **corrected the finding's remediation**:

```console
$ ssh media 'for d in /mnt/nfs /mnt/nfs/movies /mnt/nfs/downloads; do mountpoint "$d"; done'
/mnt/nfs is not a mountpoint
/mnt/nfs/movies is a mountpoint
/mnt/nfs/downloads is a mountpoint

$ ssh media 'df -h /mnt/nfs/movies/youtube /mnt/nfs/downloads/yt-staging'
192.168.2.104:/mnt/tank/movies      5.4T  1.2T  4.2T  22% /mnt/nfs/movies
192.168.2.104:/mnt/swift/downloads  769G   23G  746G   3% /mnt/nfs/downloads
```

**Both mounts are healthy today, and `/mnt/nfs` itself is not a mountpoint and
never was.** So the obvious guard — `mountpoint -q /mnt/nfs` — would fail on a
perfectly healthy system every time: a check that can never pass, which is the
mirror of the "check that cannot fail" this evaluation is built around. Any fix
must guard `/mnt/nfs/movies` and `/mnt/nfs/downloads` individually.

The consequence stays [SUSPECTED]: the mounts have not been observed failing, so
"a stale mount silently writes to the local root disk" remains inference. What is
now [VERIFIED] is that no code checks either mount, and that the naive guard is
wrong.

In fitness mode a dead mount would also make `FITNESS_LIST_SCRIPT` return empty,
and `fitness.py:259-262` then offers only "new show" — inviting a duplicate.

### F20 `*.json` and `*info.json` double-list the same file

- **Severity:** Medium — when it fires, `download_single` reports a failed
  download and then calls `session.cleanup()`, deleting a staging dir that
  already holds the good video. Latent today.
- **Grade:** [VERIFIED] — script executed under real bash with fake `yt-dlp`/`rsync`
- **Location:** `yt/remote_scripts.py:83`, `:186`; consumer `yt/single.py:111-119`
- **Disconfirming check:** the worse variant I checked for — that an unmatched
  glob is passed to rsync literally — is refuted: `shopt -s nullglob` is set at
  `:61` and `:148`. But nullglob *confirms* this finding, because both patterns
  then expand to the same `.info.json` file and it lands in the array twice.

```console
rsync: link_stat ".../Uploader-Some_Video-[abcDEF12345].info.json" failed: No such file or directory (2)
rc=23
# control, no info.json present: rc=0, "✅ Staged to SSD."
```

Latent because neither script passes `--write-info-json` — only fitness does
(`:320`), and fitness uses the safe `files=("$tmpdir"/*)`. It is one flag away
from live, and F1 is why no test would notice.

### F21 `architecture.md` §2's recovery-command claim is false for 2 of 3 modes

- **Severity:** Medium — a user hitting a NAS failure in playlist or fitness mode
  is in a recovery situation, expects the copy-pasteable command the map
  promised, and gets a bare path.
- **Grade:** [SUPPORTED] — read the doc and all three call sites
- **Location:** `docs/architecture.md:32-33`
- **Disconfirming check:** if all three modes printed it, the claim would hold.
  `single.py:130-132` does; `playlist.py:120` and `fitness.py:343` print only the
  directory.

The claim is unqualified in the document `CLAUDE.md` designates as "the map —
read it before changing anything".

### F22 `architecture.md` §4 overstates the no-interpolation invariant

- **Severity:** Medium — a doc that says quoting is solved is worse than no doc,
  because it tells the next reader not to check. It is why F6 went unnoticed.
- **Grade:** [SUPPORTED] — read `docs/architecture.md:56-57` against `single.py:44`
- **Location:** `docs/architecture.md:56-57`
- **Disconfirming check:** the fair reading is that §4 is titled "Remote-script
  contracts" and the sentence is scoped to `run_script`, which *is* airtight — I
  confirmed it quotes every positional. But the sentence as written ("The Python
  side never interpolates a value into script text, so quoting is a solved
  problem in exactly one function") is unscoped, and roughly eight remote
  commands are built as f-strings and passed to `ssh()` directly.

Honest replacement: "`run_script()` arguments are quoted; ad-hoc `ssh()` command
strings must apply `q()` to every embedded value."

### F23 The fake-SSH harness routes on substrings and a bash comment

- **Severity:** Medium — the tests are maximally sensitive to cosmetic edits and
  maximally insensitive to semantic ones, which discourages touching the scripts
  at all. It is the mirror image of F1.
- **Grade:** [VERIFIED] — comment reworded with no behaviour change; 14 tests failed
- **Location:** `tests/conftest.py:37-49`; keys at `tests/test_fitness.py:120`, `:131`
- **Disconfirming check:** if the rules keyed on behaviour, a comment change
  would be invisible. It is not.

```console
$ # changed only a bash comment: "# next episode number and digit width..."
$ uv run python -m pytest tests/test_fitness.py -q
14 failed, 21 passed
```

Related: routing on `--print '%(id)s'` means transposing the printed field order
— which in production would make duplicate detection search for the title and
re-download every video forever — passes all 8 single-mode tests. When a rule
stops matching, `FakeSSH` returns `(0, "")`: a *success with empty output*, which
degrades into a confusing error rather than a clear one.

### F24 The stdout contract is unenforced in playlist tests

- **Severity:** Medium — `yt -p URL | epm` is the consumer that breaks, and a
  stray `print()` in playlist mode ships silently.
- **Grade:** [VERIFIED] — stray `print()` probe
- **Location:** `tests/test_playlist.py:59`, `:71`
- **Disconfirming check:** single and fitness use `assert out == "<exact>"`, and
  the same probe there fails 4 tests. Playlist uses `out.count(...)` and `in`,
  both of which tolerate arbitrary extra stdout.

```console
$ # print("STRAY-PLAYLIST") as the first statement of download_playlist
$ uv run python -m pytest tests/test_playlist.py -q
17 passed in 0.52s
```

### F25 No living doc carries a status stamp

- **Severity:** Medium — the docs state throughput figures and a full pipeline
  description as present-tense fact, while the project's own record says the
  Python port was never verified end-to-end. A reader cannot tell measured from
  inherited from aspirational.
- **Grade:** [SUPPORTED] — read the head of all three living docs
- **Location:** `README.md:1-3`, `docs/architecture.md:1-3`, `CLAUDE.md:1-13`
- **Disconfirming check:** a date or "last verified" line would refute it. None
  has one. Notably the *archived* docs do carry stamps
  (`docs/archive/2026-06-20-*.md:1`), so the convention exists in this repo and is
  applied only to dead documents.

The one known caveat — "**Not verified against the live media VM in this
session**" — sits at the end of `journal/260825-python-port.md`, which F26 shows
is unreachable from anything a human reads.

### F26 The journal is unreachable from human-facing docs

- **Severity:** Medium — the journal entries are the best explanatory writing in
  the project (the feed/course rationale, the `add_help=False` trap, two
  exit-status bugs) and a human reader will never reach them.
- **Grade:** [VERIFIED] — grep for inbound links; `git log` for the broken streak
- **Location:** `journal/`, `CLAUDE.md:49-51`, `README.md:178`
- **Disconfirming check:** a link from README or `architecture.md` would refute
  the discoverability half.

```console
$ grep -rn "journal" README.md docs/
$ echo $?
1
```

The streak also broke: the last three commits (`559832d`, `84aaa65`, `199cdc6`)
have no journal entry, so the `readme.md → README.md` hatchling packaging gotcha
now survives only in a commit subject line.

### F27 The setup path omits the remote-side contract

- **Severity:** Medium — for a one-user tool the cost is a rebuild afternoon, not
  a break today. But the docs run out before the tool does.
- **Grade:** [SUPPORTED] — read `README.md:18-30` against `yt/ssh.py:44` and
  `yt/config.py:12-17`
- **Location:** `README.md:18-30`, `yt/cli.py:81-84`
- **Disconfirming check:** a statement of the SSH and mount prerequisites
  anywhere would refute it. Every *environment variable* is in fact documented —
  that box is ticked. What is missing is that SSH must succeed non-interactively
  (every call is `BatchMode=yes`, so a passphrase prompt or unknown host key
  fails with no doc-anticipated symptom), and the four NFS mounts the tool
  hardcodes, with no word on who provisions them.

### F28 "Old file will be replaced" — nothing deletes the old file

- **Severity:** Medium — silent accumulation: the category dir ends up with two
  files carrying the same `[id]`, and the next run's `find_existing` may match
  either.
- **Grade:** [SUPPORTED] — read `yt/single.py:96-135` end to end
- **Location:** `yt/single.py:102-104`
- **Disconfirming check:** an `rm` of `existing` anywhere after the message would
  refute it. There is none — the function goes straight to `run_script`.
  Replacement happens only when rsync lands on a byte-identical filename, i.e.
  when the uploader and title are unchanged; YouTube titles change routinely.

### F29 The NFS→NAS path pairing is rebuilt three times

- **Severity:** Medium — the invariant "the NAS path is the NFS path with the
  base swapped" is enforced nowhere, and the fitness spelling fails open.
- **Grade:** [SUPPORTED] — read all three constructions
- **Location:** `yt/single.py:65,124`; `yt/playlist.py:71-72`; `yt/fitness.py:339-340`
- **Disconfirming check:** a shared helper would refute it. `str.removeprefix` is
  a no-op when the prefix does not match, so if the resolve script ever returns a
  season dir not literally under `fitness_base`, `season_rel` silently becomes
  the full absolute path and `nas_season_dir` becomes a doubled path that rsync
  would happily create. F5 is one way to reach exactly that state.

### F30 Nothing exercises an end-to-end path

- **Severity:** Medium — this is the single cheapest fix available, and it closes
  F1, F7, F8 and F20 at once.
- **Grade:** [VERIFIED] — grep for every `YT_SSH` consumer
- **Location:** `yt/config.py:47-49`
- **Disconfirming check:** a test driving a real subprocess through the seam
  would refute it. The only two consumers (`tests/test_ssh.py:14`, `:24`) run
  under `@patch("yt.ssh.subprocess.run")` and assert only that the env var
  appears in argv — no process is ever launched.

```console
$ grep -rn "YT_SSH" yt/ tests/
yt/config.py:48:    """SSH binary; $YT_SSH lets tests or wrappers substitute it."""
yt/config.py:49:    return os.environ.get("YT_SSH") or "/usr/bin/ssh"
tests/test_ssh.py:14:    monkeypatch.setenv("YT_SSH", "/opt/ssh")
tests/test_ssh.py:24:    monkeypatch.delenv("YT_SSH", raising=False)
```

Both test references sit under `@patch("yt.ssh.subprocess.run")`, so no process
is ever launched through the seam.

A shell script at `$YT_SSH` that ignores the host, strips `-o BatchMode=yes` and
runs `bash -s` locally against a temp tree with fake `yt-dlp`/`rsync` on `$PATH`
would take `download_single` and `add_to_show` through the real remote scripts.
The machinery already exists at `tests/test_playlist.py:136-160`. One caveat: the
scripts need bash ≥ 4 (macOS ships 3.2 — `${t,,}` is a bad substitution there),
so this needs brew bash locally or CI-on-Linux only.

### F31 The same destination has two absolute paths across the docs

- **Severity:** Medium — a reader who takes the README literally and SSHes to
  `media` to look under `/mnt/tank` finds nothing.
- **Grade:** [SUPPORTED] — read the docs against `yt/config.py:12,17`
- **Location:** `README.md:79,142` vs `yt/cli.py:87-89` vs `README.md:160`
- **Disconfirming check:** a sentence saying they are one tree seen from two
  hosts would refute it. The *staging* pair carries exactly such a comment
  (`config.py:15-16`, "Same dir as seen from NAS locally"); the *final* pair does
  not, and no document says it either. The path actually emitted on stdout is the
  `/mnt/nfs/...` form.

### F32 `-f bestvideo+bestaudio` has no fallback

- **Severity:** Medium — a site (or an age-restricted / short-form YouTube case)
  offering only a muxed format yields "Requested format is not available" and a
  non-zero exit.
- **Grade:** [SUPPORTED] — read against yt-dlp's documented format semantics
  (`https://manpages.debian.org/unstable/yt-dlp/yt-dlp.1.en.html`)
- **Location:** `yt/remote_scripts.py:55,71,142,164,322`
- **Disconfirming check:** if `bestvideo` matched muxed formats, there would be
  no gap. It does not — `bv` is video-only, `bv*` is "best containing video", and
  `+` requires both operands. yt-dlp's own default is `bestvideo*+bestaudio/best`.
  `-f "bv*+ba/b"` is a strict superset. Five edit sites (F15).

### F33 `--remote-components ejs:github` is redundant; the real requirement is undeclared

- **Severity:** Low — reduced from Medium after checking. The runtime concern
  that carried the severity was refuted; what remains is a redundant per-run
  GitHub fetch.
- **Grade:** [SUPPORTED] — the redundancy is documented in yt-dlp's own option
  help; the runtime half was checked on the live host and refuted
- **Location:** `yt/remote_scripts.py:42,66,126,155,313` + 3 Python sites
- **Disconfirming check:** `ssh media 'command -v deno node'` — run, and it
  refuted the worry:

```console
$ ssh media 'command -v deno node bun quickjs'
/usr/local/bin/deno
/usr/bin/node
```

Both runtimes are installed, so there is no undeclared missing dependency and no
contribution to F4. The remaining point is only that the flag is unnecessary.

yt-dlp's own option help says the flag "is currently not needed if you are using
an official executable", and `UPDATE_COMMAND` installs exactly that
(`yt-dlp_linux`, a PyInstaller build that bundles `yt-dlp-ejs`). The wiki
(`https://github.com/yt-dlp/yt-dlp/wiki/EJS`) notes `ejs:github` "may not work if
GitHub and GitHub release assets are not accessible", and that Deno v2.3.0+ is
the only runtime enabled by default.

### F34 The uncovered statements are incident-time paths

- **Severity:** Low — nothing is broken; this is a statement about where the
  remaining risk sits.
- **Grade:** [SUPPORTED] — read each uncovered line
- **Location:** `yt/playlist.py:49-50,76-78,96-99`; `yt/fitness.py:167-168,237-238,259,265-268,285-286,368-369`
- **Disconfirming check:** if the misses were dead code, they would not matter.
  They are not: `playlist.py:76-78` is `mkdir -p` failing on the media VM — i.e.
  **the NFS mount is down**, the single most likely real-world failure, and the
  branch deciding `cleanup(staging=False)` there has never run.

### F35 The category mode's Jellyfin outcome is undocumented

- **Severity:** Low — the reader cannot judge whether `-y youtube` gets them a
  watchable entry or just a file on a disk.
- **Grade:** [SUPPORTED] — read all three mode sections
- **Location:** `README.md:32-55`
- **Disconfirming check:** the other two modes *do* document it (playlist: "add
  that directory manually as a Jellyfin movie library"; fitness: in detail), so
  the omission is specific rather than a house style. Part of why F9 is hard to
  answer.

### F36 Fitness stages `*` while the other modes stage a whitelist

- **Severity:** Low — correct today, for a reason recorded nowhere.
- **Grade:** [SUPPORTED] — read all three `files=` lines and `git log`
- **Location:** `yt/remote_scripts.py:352` vs `:83`, `:186`
- **Disconfirming check:** the asymmetry looks like a missing fix, and is not:
  commit `892e43f` added srv3/ttml cleanup to fitness only, *because* fitness
  stages everything and the other two do not. Consequence: fitness will ship any
  future unanticipated sidecar into the Jellyfin season dir — the exact problem
  `remote_scripts.py:79-80` exists to prevent — and a maintainer reading the three
  side by side will reasonably conclude the other two are missing a fix.

### F37 `ssh.lines()` is dead code

- **Severity:** Low — harmless.
- **Grade:** [VERIFIED] — no caller in `yt/` or `tests/`; it is the only uncovered
  line in the module (`ssh.py 33 1 97% 69`) and is absent from `architecture.md:44`'s
  API list
- **Location:** `yt/ssh.py:67-69`
- **Disconfirming check:** every call site open-codes `result.stdout.splitlines()`
  — I grepped all seven. A single caller anywhere would refute it.

```console
$ grep -rn "lines(" yt/ tests/ --include="*.py" | grep -v splitlines
yt/jellyfin_nfo.py:56:def _prose_lines(paragraph: str) -> list[str]:
yt/jellyfin_nfo.py:104:        lines = _prose_lines(para)
yt/ssh.py:67:def lines(result: subprocess.CompletedProcess[str]) -> list[str]:
tests/test_fitness.py:31:    def test_show_without_seasons_and_old_four_column_lines(self) -> None:

$ uv run python -m pytest --cov=yt -q | grep "yt/ssh.py"
yt/ssh.py                 33      1    97%   69
```

`yt/ssh.py:67` is a definition with no matching call, and line 69 — its body — is
the module's only uncovered line.

### F38 `yt --update` pins the channel upstream calls "often stale"

- **Severity:** Low — the command works and is a legitimate install shape.
- **Grade:** [SUPPORTED] — upstream README and release API
- **Location:** `yt/remote_scripts.py:361-368`
- **Disconfirming check:** if stable were the recommended channel the pin would
  be right. yt-dlp's README says stable is "often 'stale' and prone to external
  breakage" and nightly is "the recommended channel for regular users"; the
  nightly repo publishes the identical asset name, so this is a one-URL change.
  The comment at `:361-362` gives the motive as the apt package lagging and then
  403ing — which is the exact problem nightly addresses.

Worth recording in the comment: because the binary is installed `-o root -g root`
in `/usr/local/bin`, `yt-dlp -U` can never work for a non-root user, so `yt
--update` is the only update route on that box. That is a deliberate consequence,
not a defect.

### F39 `yt --update` installs an unverified binary as root

- **Severity:** Low — trust rests on TLS and GitHub; correct in structure (no
  curl-pipe-to-shell, `-f` fails on HTTP errors, `set -e` stops the chain).
- **Grade:** [SUPPORTED] — read `yt/remote_scripts.py:363-367`
- **Location:** `yt/remote_scripts.py:363-367`
- **Disconfirming check:** a checksum step would refute it; there is none.
  Upstream publishes a `SHA2-256SUMS` file, so this is three more lines. `$tmp`
  also leaks if the install step fails.

### F40 `_xml()` does not escape `"`

- **Severity:** Low — a quote in that field produces a malformed `.nfo` that
  Jellyfin silently ignores.
- **Grade:** [SUPPORTED] — read `yt/jellyfin_nfo.py:122-123` and its use at `:155`
- **Location:** `yt/jellyfin_nfo.py:122-123`, `:155`
- **Disconfirming check:** the escaped value is used inside an XML *attribute*
  (`<uniqueid type="…" default="true">`), where `"` is significant — unlike the
  bash-side escaper at `remote_scripts.py:262,266`, which writes element text
  where quotes are harmless. The two escapers should agree.

### F41 `CLAUDE.md`'s README-table wording invites drift

- **Severity:** Low — the table is correct today.
- **Grade:** [VERIFIED] — table diffed programmatically against `yt.config.CATEGORIES`;
  exact match on content and order
- **Location:** `CLAUDE.md:30-33`
- **Disconfirming check:** the `--help` block genuinely *is* generated
  (`cli.py:95`); the README table is not, and only a trailing parenthetical says
  so. An agent skimming "the flag, validation, help text and README table" derive
  from one line will ship a stale README.

```console
$ uv run python -c "...parse README rows, compare to yt.config.CATEGORIES..."
README: [('g', 'training', 'Training and gym/workout videos'), ('y', 'youtube', 'General YouTube content'), ...]
CODE  : [('g', 'training', 'Training and gym/workout videos'), ('y', 'youtube', 'General YouTube content'), ...]
MATCH EXACT (content+order): True
```

### F42 `--help` omits the `nas` host and `ffprobe`

- **Severity:** Low — `--help` is the doc a user reaches for at failure time, and
  it understates the dependency set relative to the README (which gets both right).
- **Grade:** [SUPPORTED] — read `yt/cli.py:81-84` against `yt/session.py:60` and
  `yt/single.py:51`
- **Location:** `yt/cli.py:81-84`
- **Disconfirming check:** stage 2 runs `NAS_SCRIPT` on `NAS_HOST` on every
  successful download, so the `nas` alias is not optional.

### F43 `--help` writes to stderr and no doc says so

- **Severity:** Low — deliberate design (consistent with the stdout rule), but
  `yt --help | less` and `yt --help > notes.txt` both silently produce nothing.
- **Grade:** [VERIFIED] — `cli.run` executed under captured streams for `[]`,
  `help` and `--help`: all three gave `stdout_bytes=0`, `stderr_lines=82`
- **Location:** `yt/cli.py:138`, `:142`
- **Disconfirming check:** any byte on stdout would refute it. There are none.

```console
$ uv run python -c "...cli.run(['--help']) under redirect_stdout/redirect_stderr..."
rc=0 stdout_bytes=0 stderr_lines=82
```

The behaviour is intended and consistent with the stdout rule; the finding is the
missing note.

### F44 `architecture.md` does not link its own archive

- **Severity:** Low — the superseding doc is a dead end for "why was playlist mode
  designed this way", all of which is in the archived design doc.
- **Grade:** [SUPPORTED] — `grep -n archive docs/architecture.md` → no match
- **Location:** `docs/architecture.md`
- **Disconfirming check:** both archived files *do* carry the required "superseded
  by" header, so the convention's status half is satisfied; the inbound-link half
  is satisfied only by `README.md:178` pointing at the directory. One line in §3
  fixes it.

### F45 `epm` is never explained

- **Severity:** Low — it justifies the most invasive design constraint in the
  codebase and the reader cannot look it up.
- **Grade:** [SUPPORTED] — four references across every doc; the only gloss is
  `yt/cli.py:78` ("Pipe to epm for photo extraction")
- **Location:** `CLAUDE.md:17`, `README.md:63`, `docs/architecture.md:22`, `yt/cli.py:78-79`
- **Disconfirming check:** a sentence saying what `epm` is, where it comes from,
  and that it is optional would refute it.

### F46 The playlist slug fallback is undocumented

- **Severity:** Low — recoverable and prompt-gated.
- **Grade:** [SUPPORTED] — read `yt/playlist.py:66`
- **Location:** `yt/playlist.py:66`
- **Disconfirming check:** `slug = _confirm_slug(slugify(title) or "playlist")` —
  when the title fetch fails or slugifies empty, the suggested directory is
  literally `playlist`, and every subsequent title-less playlist merges into it.
  `README.md:133-134` says only that `yt` "derives a URL-safe slug".

### F47 README's duplicate-detection paragraph describes single mode only

- **Severity:** Low — a reader could expect a playlist re-run to upgrade a 480p
  item to 1080p; it will not, it will skip it as archived.
- **Grade:** [SUPPORTED] — read `README.md:15-16` against all three modes
- **Location:** `README.md:15-16`
- **Disconfirming check:** playlist dedupes via `--download-archive`
  (`playlist.py:73`) and fitness by YouTube id across the show
  (`fitness.py:290`); neither compares quality. The paragraph sits in the preamble
  before any mode is introduced, so it reads as a property of `yt`.

### F48 Multi-video fitness downloads would mismatch episode numbers

- **Severity:** Low — latent; one URL almost always means one video.
- **Grade:** [SUSPECTED] — inferred from reading both sides; never observed
- **Location:** `yt/remote_scripts.py:343-350` vs `yt/jellyfin_nfo.py:180`
- **Disconfirming check:** what would settle it is running `yt -f` on a URL that
  yields two video files and comparing filenames to nfo contents. The script
  computes one `prefix` with a single `$episode` and applies it to every file,
  while the helper writes `episode + i`. For a `feed` season the helper counts
  *up* where the season numbers *down*, so the second video would take the number
  the next download expects.

### F49 EOF handling diverges between playlist and fitness prompts

- **Severity:** Low — defensible as a scripting affordance, but undocumented.
- **Grade:** [SUPPORTED] — read `yt/playlist.py:42-43` against `yt/fitness.py:253-256`
- **Location:** `yt/playlist.py:42-43`
- **Disconfirming check:** `yt -p URL < /dev/null` creates a library directory
  from an auto-derived slug with no confirmation; `yt -f URL < /dev/null` refuses.
  Both modes present themselves as "confirm before writing".

### F50 Port artefacts a reader trips over

- **Severity:** Low — individually cosmetic; collectively they are where a Python
  reader has to reconstruct a shell idiom to understand the intent.
- **Grade:** [SUPPORTED] — read each cited line
- **Location:** `yt/session.py:32-43,62-69`; `yt/cli.py:100,187`; `yt/fitness.py:70,169,184-188,51`
- **Disconfirming check:** `Session` is the load-bearing one: `__enter__` returns
  `self` and does nothing, `open()` does the `mktemp`, and `__exit__` *raises*.
  That is the zsh `trap` transliterated, and it is the direct cause of F12. Also:
  `split_target` loops over `ORDERS` without `break`, so a season can never be
  named `feed` or `course`; `fitness.py:51` raises an uncaught `ValueError` if the
  `Season NN` marker is absent; `cli.py:187`'s `assert` is stripped under `-O`.

### F51 The episode NFO has three inert fields and omits two useful ones

- **Severity:** Low — nothing is broken. `<stem>-thumb.jpg` is exactly right and
  `lockdata=false` is the correct choice.
- **Grade:** [SUPPORTED] — checked against Jellyfin's own parsers
  (`BaseNfoParser.cs`, `EpisodeNfoParser.cs`, `EpisodeLocalImageProvider.cs`)
- **Location:** `yt/jellyfin_nfo.py:137-157`
- **Disconfirming check:** all 11 emitted elements are in the parser's recognised
  set, so nothing is rejected. Inert: `default="true"` on `<uniqueid>` (only
  `type` is read), `<studio>` (surfaced at series level only), and `<sorttitle>`
  set equal to `<title>` (episode ordering uses `IndexNumber`). Worth adding:
  `<genre>` (the only field that would change navigation) and `<dateadded>`
  (drives "Recently Added"; without it a backfill lands every episode on one day).
  One sharp edge: `<aired>` is parsed with `TryReadDateTimeExact` against the
  server's `ReleaseDateFormat`, so if an admin changes that setting the date fails
  silently.

## 4. Test suite results

Runner: pytest 9.1.1 via `uv run python -m pytest` (not bare `uv run pytest` — a
pyenv-global pytest shadows the venv's). Run in the evaluation worktree.

```console
$ uv run python -m pytest --cov=yt -q
........................................................................ [ 54%]
.............................................................            [100%]
Name                   Stmts   Miss  Cover   Missing
yt/cli.py                 93      2    98%   142-143
yt/config.py              34      1    97%   56
yt/cookies.py             30      0   100%
yt/fitness.py            262     17    94%   68, 115, 146, 167-168, 199, 237-238, 259, 265-268, 285-286, 368-369
yt/jellyfin_nfo.py       124      8    94%   60, 84, 86, 109, 200-202, 206
yt/playlist.py            89      9    90%   49-50, 76-78, 96-99
yt/remote_scripts.py       7      0   100%
yt/session.py             48      0   100%
yt/single.py             102      0   100%
yt/ssh.py                 33      1    97%   69
yt/ui.py                  40      0   100%
TOTAL                    862     38    96%
133 passed in 0.47s

$ uv run ruff check . && uv run ruff format --check .
All checks passed!
33 files already formatted

$ uv run pyright
0 errors, 0 warnings, 0 informations
```

Nothing fails. **The `remote_scripts.py 100%` row is the report's most misleading
number**: it measures that the module's seven string constants were *assigned*,
not that any script was run. See F1.

## 5. Project overview

A single-user Python 3.13 CLI (`uv tool install -e .`, entry point
`yt.cli:main`), 862 statements across 11 modules, zero runtime dependencies.

It orchestrates work on two remote hosts over SSH: `media` (a VM that runs
yt-dlp and has the NFS mounts) and `nas`. Every remote call funnels through
`yt/ssh.py`; the actual work lives in seven bash scripts held as string constants
in `yt/remote_scripts.py` and executed via `bash -s -- args…` with `shlex.quote`d
positionals. Downloads use a two-stage SSD-staged transfer — media VM → SSD NFS
(~552 MB/s) → NAS-local HDD copy (~1.6 GB/s) — to avoid a slow direct-to-HDD path.

Three modes: single (`yt -<cat> URL` → `youtube/<category>/`), playlist (`yt -p`
→ a per-playlist library dir), and fitness (`yt -f [Show/Season] URL` → a Jellyfin
*Health & Fitness* Shows episode with `.nfo` and thumbnail, written by
`yt/jellyfin_nfo.py` piped to the media VM's `python3`).

Ported 1:1 from a 1,300-line zsh script in August 2026.

## 6. Strengths

1. **Zero runtime dependencies** (`pyproject.toml:7`). The CLI is stdlib-only,
   so there is no supply chain to attack on the Mac side and nothing to keep
   patched. This is the single best structural decision in the project.
2. **The CI pipeline is honest.** `.github/workflows/test.yml:13-17` runs `uv
   sync`, `ruff check`, `ruff format --check`, `pyright` and `pytest` as five
   separate `run:` steps — no pipes, no `continue-on-error`, no `|| true`. Every
   step can actually go red. This is rarer than it should be, and F16's two gaps
   are small against it.
3. **`architecture.md` §4 is accurate under checking.** The remote-script stdout
   contracts — six printf lines in order from `FITNESS_RESOLVE_SCRIPT`, the exit
   4/5/6 meanings, "exit 0 with no output = archived skip, exit 3 = genuine
   failure" — were verified line by line against `remote_scripts.py` and hold. So
   does the README category table, diffed programmatically against `CATEGORIES`.
   Documentation that survives this kind of check is not the norm.
4. **`ssh.run_script()` genuinely quotes every positional** (`yt/ssh.py:54-57`),
   confirmed by constructing a command with a hostile show name. The invariant
   holds where it is implemented; F6 is about the call sites that bypass it.
5. **One project rule is structurally enforced.** `tests/test_jellyfin_nfo.py:115-124`
   runs the helper standalone over stdin — mirroring how the media VM invokes it —
   and asserts `"import yt" not in script`. That is what enforcement looks like,
   and it is the model for the rules in F16's register that lack it.
6. **Adding a category really is one line.** `CATEGORIES` in `config.py` drives the
   flag, the validation and the generated help text (F41 is only about the README half).
7. **The journal entries are excellent** where they exist — `260823-fitness-mode.md`
   records the feed/course rationale and two exit-status traps with enough detail
   to act on. F26 is about reach, not quality.

## 7. Weaknesses

The through-line is **assurance concentrated where the risk is not**. 133 tests
and 96% coverage sit almost entirely on the Python orchestration layer, which is
thin and mostly correct; the seven bash scripts that actually download, rename,
stage and transfer files are exercised once (F1, F30). Every one of F2, F5, F20
and F48 lives in that unexercised layer, and F1 is why none of them would be
caught by a regression.

The second theme is **failure paths that report the wrong thing**: F4 turns a
failed probe into a success, F10 turns a truncated playlist into a complete one,
F18 turns an unreachable host into a missing binary, F13 likely turns a working
scan into a warning. Individually Medium; together they mean the tool's error
output cannot be trusted to distinguish causes, which is what makes F19's
undetected-mount scenario plausible rather than paranoid.

Third, **the project's stated rules outrun its checks** (section 8). Four rules in
`CLAUDE.md`; one enforced, one partial, two prose-only — and one of the
prose-only ones is already violated (F6, F22).

The documentation is better than the average for a personal tool and its errors
are concentrated in a specific place: claims about *behaviour across all three
modes* that are true of single mode only (F21, F47, and F9's missing guidance).

## 8. NFR register

| Requirement | Where stated | How enforced |
| --- | --- | --- |
| stdout carries final file paths only | `CLAUDE.md:17`, `architecture.md:21`, `ui.py:1` | **Partial** — exact-stdout asserts in `test_single.py:28,52,98` and `test_fitness.py:137`; playlist asserts are containment-only (F24); and the rule is broken at runtime in fitness (F3) |
| All remote calls go through `yt/ssh.py`; never `subprocess` elsewhere | `CLAUDE.md:19` | **prose only** — true today by grep, but no test or lint rule |
| Remote scripts get quoted positionals; never interpolate into script text | `CLAUDE.md:19-21`, `architecture.md:56` | **prose only** — and already violated at `single.py:44`, `fitness.py:206` (F6) |
| `jellyfin_nfo.py` stays stdlib-only, no `from yt import …` | `CLAUDE.md:23` | **Enforced** — `tests/test_jellyfin_nfo.py:115-124` runs it standalone and asserts the import is absent |
| `clean_overview()` mirrors proxmox-setup's `migrate.py` | `CLAUDE.md:24` | **prose only** — cross-repo; not enforceable from here |
| Staging kept after NAS/nfo failure, removed after download failure | `CLAUDE.md:26-28` | **Partial** — 2 of 4 paths asserted (F8) |
| `-h` is humanity, not help | `CLAUDE.md:29` | **Enforced** — `tests/test_cli.py:34` |
| Tests never open a real SSH connection | `CLAUDE.md:41` | **Enforced structurally** — `conftest.py` patches `yt.ssh._execute`; there is no real-ssh path to take |
| Lint, format and types clean | `CLAUDE.md:35-38` | **Enforced** — three separate CI steps, each able to fail |
| Test coverage | implied by `--cov=yt` in CI | **prose only** — no `fail_under` anywhere (F16) |
| Reproducible dependencies | `uv.lock` committed | **Partial** — lockfile exists and is current, but CI runs `uv sync`, not `--frozen` (F16) |
| Docs are accurate; `architecture.md` is "the map" | `CLAUDE.md:12-13` | **prose only** — no stamp, no date, no link check (F25) |

**Un-gated code inventory:** the seven bash scripts in `yt/remote_scripts.py` are
the whole of it — only `PLAYLIST_ITEM_SCRIPT` is executed for real
(`tests/test_playlist.py:163-206`), and `UPDATE_COMMAND` is never executed by any
test. `yt/jellyfin_nfo.py` is *not* in this inventory: it is genuinely gated.
There is no Dockerfile, no IaC, no cron, and no deploy-time workflow, so nothing
else ships unread. Invariants that hold only in the deployed environment: the
four NFS mounts, `ffprobe` and `python3` on the media VM, `rsync` on the NAS, and
a JS runtime for yt-dlp (F33) — none checked, none documented.

**NFRs absent rather than unenforced:** there is no observability requirement of
any kind — no structured logging, no rule about what must never be logged (the
cookie path and the Jellyfin key are handled correctly, but by construction
rather than by stated policy), and no way to reconstruct what a past run did.
Accessibility is not applicable (CLI). No performance NFR, which is fine — the
throughput figures in the docs are rationale for a design choice, not a target.

## 9. Onboarding assessment

The project states no explicit onboarding bar, so this is measured against the
implicit one: could someone rebuild and run this from the docs?

**What I could not determine from the docs alone.** Four things, all requiring
code. Which Jellyfin library indexes a *category* download — that fact is nowhere
in the repo (F35). Whether `/mnt/nfs/...` and `/mnt/tank/...` are the same files —
inferable only from a comment on the *staging* constants two lines above the
final ones (F31). What happens on a NAS failure in playlist and fitness mode —
`architecture.md` answered confidently and wrongly (F21). And what `-g` actually
was versus `-f`, which is the question that started this run and which the user
themselves could not answer from memory ("`yt -g` i think").

**Claims I distrusted enough to check.** Three, and all three held, which raised
confidence in the docs materially: `architecture.md` §4's remote-script contracts
(verified line by line — the best documentation in the repo), the README category
table (diffed programmatically, exact match), and all twelve documented example
commands (executed through the real parser with modes mocked — every one
dispatches correctly, including the `-h` humanity trap). The README's "133 tests"
claim is also exactly right.

**Where I got lost.** Looking for an ADR log, then for a link to `journal/` from
anything a human reads — neither exists (F26). The journal was found only via
`CLAUDE.md`, which is addressed to agents. Then looking for a "which mode do I
use?" section, which is the question three modes force on every use, and finding
nothing (F9). The README is organised by feature rather than by decision.

**Would the setup path work? I read it; I did not execute it.** I deliberately
did not run `uv tool install -e .` — it mutates the user's tool environment. The
install line itself is sound (`-e` is real, `pyproject.toml:9-10` defines the
entry point). Beyond it, **a cold reader could not get this working from the docs
alone.** The local half is fine. The remote half is undocumented: no statement
that SSH must succeed non-interactively (every call is `BatchMode=yes`), no
mention of the four hardcoded NFS mounts, and no pointer to whatever provisions
them except in passing for `yt --update` (F27). On this machine, against standing
infrastructure, everything works. On a fresh machine the docs run out before the
tool does.

## 10. Assessment dimensions

- **Simplicity:** 3/5 — the module split is clean and each file does one thing,
  but the three modes carry near-duplicate download/stage/transfer logic and the
  yt-dlp flag block is copied across 8 sites with no shared constant (F15). Named
  weakness I would fix before adding a fourth mode.
- **Robustness:** 2/5 — present where it was easy, missing where it matters. No
  SSH timeout at all (F17), no mount check (F19), a staging leak that accumulates
  forever (F7), and a failure path that reports success (F4). The two-stage
  transfer design itself is sound and rsync's temp-then-rename means no truncated
  file ever appears under a final name.
- **Security:** 3/5 — adequate for a single-user LAN tool with named weaknesses:
  zero runtime dependencies, correct cookie permissions (`umask 077`), correct
  Jellyfin auth, no secrets in history, and `run_script` quoting everything —
  against two raw interpolations (F6) and an unvalidated path segment (F5).
- **Flexibility:** 3/5 — adding a category is genuinely one line, which is the
  extension point that gets used. Changing a yt-dlp flag correctly requires 8
  edits and nothing fails if you miss one (F15).
- **Test coverage:** 2/5 — 133 tests and 96% line coverage that do not cover the
  component holding the risk. Five destructive mutations to the remote scripts
  left the suite green (F1); the harness routes on comments (F23); nothing runs
  end to end though the seam exists (F30). The number is high and the assurance
  is low, which is worse than a low number.
- **Documentation accuracy:** 3/5 — the two highest-risk claims were verified
  correct, which is a real result. Against that: §2's recovery-command guarantee
  is false for two of three modes (F21), §4 overstates the quoting invariant
  (F22), and the duplicate-detection paragraph describes one mode as if it were
  three (F47).
- **Documentation completeness:** 3/5 — every environment variable is documented
  somewhere a reader would look, and the fitness mode is documented in genuine
  detail. The remote-side prerequisites are absent entirely (F27), and so is any
  guidance on which mode to use (F9).
- **Deployment quality:** 3/5 — CI gates four real checks with no escape hatches,
  and `uv.lock` is committed and current. Held back by no coverage floor and an
  unfrozen `uv sync` (F16), and by remote-host assumptions that are neither
  checked at runtime nor documented.
- **Observability:** 2/5 — the stderr progress output is genuinely good for a
  human watching a download, with elapsed timers and clear stage markers. But
  four separate failures report a cause other than the real one (F4, F10, F13,
  F18), there is no structured logging, and no record of a past run survives it.
- **Enforcement:** 2/5 — of the four rules `CLAUDE.md` states, one is genuinely
  enforced, one is partial, and two are prose-only — one of which is already
  violated (F6). Plus a measured-but-ungated coverage number (F16). The project
  states more than it checks, which is the register in section 8 expressed as a
  score.

Accessibility is omitted: this project serves no browser pages.

## 11. Dependency audit

Manifests inspected: `pyproject.toml` and `uv.lock`.

**Runtime dependencies: none.** `pyproject.toml:7` is `dependencies = []`. The
CLI is stdlib-only, which removes this entire class of risk.

The 12 locked dev-group packages were checked against OSV.dev. `pip-audit` could
not run in this environment (its isolated-venv `ensurepip` aborts with SIGABRT),
so the database was queried directly with `VIRTUAL_ENV` unset and versions read
from the project's own `uv export` — this matters because a stale virtualenv on
`$VIRTUAL_ENV` has produced false vulnerability reports in evaluations before.

```
colorama 0.4.6, coverage 7.15.4, iniconfig 2.3.0, nodeenv 1.10.0, packaging 26.3,
pluggy 1.6.0, pygments 2.21.0, pyright 1.1.411, pytest 9.1.1, pytest-cov 7.1.0,
ruff 0.16.4, typing-extensions 4.16.0
→ total advisories: 0 over 12 locked packages
```

```console
$ uv lock --check
Resolved 13 packages in 5ms
```

Nothing outdated in a way that matters; nothing vulnerable. The one dependency
that *is* a live concern is not in any manifest: yt-dlp on the media VM, pinned
to the stable channel upstream calls "often stale" (F38), plus an undeclared JS
runtime requirement (F33).

## 12. Gap analysis

1. **A real-bash test harness.** The highest-value missing thing in the project.
   `tests/test_playlist.py:136-160` already has the fixture shape (`FAKE_YTDLP`,
   `FAKE_RSYNC`, `fake_bin`); generalising it behind `$YT_SSH` would close F1, F7,
   F8 and F20 together. Needs bash ≥ 4, so brew bash locally or Linux-only in CI.
2. **A coverage floor and `uv sync --frozen`** (F16) — two lines.
3. **Validation of user-supplied path segments** in fitness mode (F5); `playlist.py`
   already has the pattern to copy.
4. **Runtime preflight** distinguishing "host unreachable" from "tool missing"
   (F18), and checking the NFS mount (F19).
5. **A "which mode do I use?" section** (F9), and the legacy note on
   `training/` the retirement needs.
6. **A link from README/architecture.md to `journal/`** (F26), and a status stamp
   convention applied to living docs rather than only archived ones (F25).
7. **No structured logging or run record** — not obviously worth adding for a
   personal tool, but it is why F4 and F10 are hard to notice after the fact.

## 13. Architectural assessment

**The two-stage SSD-staged transfer is the right design and is well justified.**
`architecture.md:35-36` records the alternatives and their measured costs (direct
rsync to HDD NFS ~50 MB/s; direct download to HDD makes the mux slow; `mv`
between NFS mounts sends data over the network twice). That is exactly the
rationale record the rest of the docs lack.

**Bash-strings-over-SSH is defensible** for a 1:1 port and keeps the remote side
dependency-free, but it is what makes F1 possible: the scripts are the product
and they are opaque to the test suite. The `bash -s -- args…` calling convention
with `shlex.quote`d positionals is the right choice within that approach and is
correctly implemented — the failures are at the eight ad-hoc `ssh()` call sites
that bypass it.

**The Jellyfin integration is current and correctly built.** `POST /Library/Refresh`
with `Authorization: MediaBrowser Token="…"` is the recommended scheme and is
unaffected by the 12.0 change that disables legacy authorization — the deprecated
forms (`X-Emby-Token`, `X-MediaBrowser-Token`, lowercase `api_key=`) are not used.
Verified against `https://repo.jellyfin.org/files/openapi/stable/jellyfin-openapi-10.11.11.json`
and `https://api.jellyfin.org/openapi/jellyfin-openapi-stable.json`. The NFO
fields are all in Jellyfin's recognised set and `<stem>-thumb.jpg` matches
`EpisodeLocalImageProvider`. The open question is the blocking-endpoint/timeout
pairing (F13). Note two doc URLs the problem space commonly cites now 404:
`https://jellyfin.org/docs/general/server/api-keys/` and
`https://jellyfin.org/docs/general/server/media/images/`.

**The yt-dlp integration is the weakest area.** The subtitle configuration has
never worked (F2, verified live), the format selector has no fallback (F32), the
language glob is broader than intended (F14), the EJS flag is redundant while its
real requirement is unchecked (F33), and the update channel is the one upstream
recommends against (F38). None is individually severe; together they say this
integration has not been revisited against upstream since it was written, and
F15 is why revisiting it is more work than it should be.

## 14. Methodology and limitations

**Shape.** Standard team, 4 subagents dispatched in parallel — structure/quality
plus scoped web research, tests/reliability, security/robustness/deployment, and
a product-owner documentation pass. No UI agent (this is a CLI, so Engineer 5 and
the Accessibility dimension were both correctly omitted, not skipped). No wide
survey: this repo is one coherent thing with 11 modules, so splitting it into
areas would have invented boundaries. Steps 1, 2.5, 2.6 and all of Step 3 were
done by the lead.

**Verification.** Every load-bearing finding was re-checked by the lead with a
*different* observation than the one that produced it. That changed outcomes:
F2 was promoted from [SUPPORTED] to [VERIFIED] by a live yt-dlp run and an
independent ffmpeg test; F13, F19, F33 and F48 were graded down to [SUSPECTED]
because the observation that would settle them requires connecting to hosts I did
not touch; F22 was graded down from the reporting agent's High to Medium after
reading the surrounding heading, which partly scopes the claim; and my own
disconfirming check on F20 (that unmatched globs might be passed literally) came
back refuted by `shopt -s nullglob` while *confirming* the finding itself. Two
agents independently reported F6; that agreement is not why it is graded
[VERIFIED] — I read both call sites myself.

**What was not covered.**

1. **No connection to `media`, `nas`, or the Jellyfin server.** Every claim about
   those hosts' actual state — mount status, whether Deno/Node is installed,
   whether `yt --update` has been run recently, how long a library scan takes — is
   inference from code. F13, F19 and F33 are [SUSPECTED] for exactly this reason
   and each names the one command that would settle it.
2. **F2's downstream half is unsettled.** The flag combination provably fails and
   yt-dlp exits 1; whether the mkv survives and the retry fires was not
   established, because my second live test was cut off by an HTTP 429 and I was
   then rate-limited. One real run settles it.
3. **`clean_overview()` was not compared against proxmox-setup's `migrate.py`.**
   `CLAUDE.md:24` requires them to stay in step; that repo is outside this
   worktree and was not opened. Nobody was briefed on it, so the silence here is
   a gap, not a clean bill.
4. **The NFO regexes were not mutation-tested.** `jellyfin_nfo.py`'s promo-stripping
   heuristics (`_prose_lines`, lines 56-109) are the one place with a genuinely
   good real-execution test, and its *quality* was assessed but its edge cases
   were not probed.
5. **No mutation testing of the Python layer.** F1 establishes that the bash
   scripts are unprotected; the equivalent exercise was not run against `yt/*.py`,
   so "the Python side is well tested" is an impression from reading the suite,
   not a measurement. F23 and F24 are the two places where it demonstrably is not.
6. **`journal/260620`, `260621` and both archived design docs were read only in
   part**, so findings about historical rationale are based on the entries that
   were read in full (`260506`, `260823`, `260825`).

**One process note.** During this evaluation I wrote a check whose exit code was
consumed by a pipe (`ffmpeg … | head`), which reported success on a command that
had failed — the same defect this report records as F10. I caught it and re-ran
without the pipe; the corrected result is what section 3 quotes. Recording it
because it is evidence for how easily that pattern passes review.
