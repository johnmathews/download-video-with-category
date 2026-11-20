# Fail early when the destination is unreadable

> Purpose: why every download mode now checks the final directory on both hosts before downloading.

## 1. What happened

On 2026-11-19 at 22:54:30 CET the TrueNAS VM crashed and reset itself (most likely a kernel panic;
`kernel.panic=10`, no dump captured). It came back with its passphrase-encrypted datasets locked, so
`tank/movies` was not mounted and the media VM's NFS mount of it went stale.

`yt -h <url>` run two minutes later:

- reported "✓ No existing download found" — `find_existing` ended `2>/dev/null | head -1`, so the
  `Stale file handle` error vanished and the pipeline took head's exit status 0;
- downloaded and staged 600 MB;
- failed only at stage 2: `mkdir: cannot create directory '/mnt/tank/movies/youtube': Operation not
  permitted` (the unmounted dataset's mountpoint is an immutable placeholder).

## 2. Decisions

- **Check both views.** The media VM reads the destination over NFS (duplicate check, playlist archive) and
  the NAS writes it locally (stage 2). Either can be broken while the other looks fine, so
  `check_destinations()` tests `REMOTE_FINAL_BASE` on `media` and `NAS_FINAL_BASE` on `nas`.
- **`ls -A`, not `test -d`.** Reading the directory surfaces the kernel's reason ("Stale file handle",
  "No such file or directory") in the message instead of a bare false.
- **`timeout -s KILL 15`.** A hard NFS mount with its server down blocks reads indefinitely; SIGTERM does
  not interrupt that wait, SIGKILL does. Verified `timeout -s KILL` exits 137 on both hosts.
- **Ad-hoc `ssh()` rather than a `remote_scripts.py` script.** The check is three shell tests, and keeping
  it out of `bash -s` leaves the existing tests' call accounting (which find the download script as the
  first `bash -s`) meaningful. Its one value goes through `q()`.
- **Placed after local validation, before `Session().open()`.** Nothing is uploaded or created when it
  fails. In fitness mode it runs after the show-name check, so a bad name is still rejected without
  touching the network beyond the yt-dlp check.
- **`find_existing` returns `None` for a failed search** with no match, and single mode stops with
  "Could not search …". A match still counts when find also hit an error elsewhere. A category directory
  that does not exist yet is guarded with `[ ! -e dir ] ||` so a first download into it is not an error.

## 3. Not changed

`fitness._find_in_show` has the same `2>/dev/null | head -1` shape. The preflight covers its base directory,
so the incident case is caught; the narrower case (one unreadable show directory) still reads as "not in this
show".

## 4. Verified

Real command run against both hosts: usable roots pass; a missing NAS path exits 3 with the `ls` message;
a non-writable directory exits 4. Tests: 18 new in `tests/test_destination.py`, including the exact command
string under a real `/bin/sh` against temp directories and a hostile path. Removing the call from
`single.py` fails `test_single`. Full suite 238 passed; coverage 96.13% (floor 94%); ruff and pyright clean.
