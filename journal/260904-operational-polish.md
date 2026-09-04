# 2026-09-04 — Operational polish: coverage floor, SSH timeouts, and a preflight that tells the truth

Follow-on to `260904-retire-training-category.md`, working the top of that pass's deferred list.
Three small fixes, one finding settled without writing any code, and the evaluation report moved
somewhere it will survive.

## What landed

**A coverage floor that can actually fail (F16).** `--cov=yt` measured coverage and gated nothing:
it could have fallen from 96% to 40% with CI still green. `fail_under = 94` in `pyproject.toml`,
set just under the current 95.85% so it catches a regression without going red on a wobble.
Proved it goes red rather than assuming — a gate shipped without that proof is decoration:

```
floor 99 (above actual): RED   exit=1  FAIL Required test coverage of 99.0% not reached
floor 94 (restored):     GREEN exit=0
```

Worth being explicit about what this floor does *not* cover: it measures Python only. The bash in
`remote_scripts.py` is where the files actually move, and `coverage.py` cannot see it — the
mutation results in `test_remote_scripts.py` are the evidence there, not this percentage.

Also `uv sync --frozen` in CI, so a stale `uv.lock` fails instead of being silently re-resolved.

**SSH connection options (F17).** There were none beyond `BatchMode`, so an unreachable VM blocked
for the kernel's TCP timeout and a frozen one hung `yt` forever with no output — the exact failure
a long download invites. Measured against an unroutable address (RFC 5737 `192.0.2.1`):

```
without ConnectTimeout: still waiting when I capped it at 25s
with:                   exit=255 after 10s
```

`ServerAliveInterval=30` x `ServerAliveCountMax=6` gives three minutes of silence before giving up.
Deliberately generous: a NAS busy with a large rsync can be quiet for a while, and dropping a good
transfer is worse than waiting. The options live in one `SSH_OPTIONS` list so every call gets them.

**A preflight that distinguishes its two failures (F18).** `check_ytdlp_installed()` treated any
non-zero exit as "yt-dlp not found on media VM / Install it with: yt --update". ssh uses 255 for
its own failures, so a host that was simply down produced advice that would fail the same way —
and this is the *only* remote preflight, so it is the first thing you see when the VM is off.

## Settled without writing code

**F13 — the Jellyfin scan timeout.** The plan was a live `yt -f` run to see whether the blocking
`/Library/Refresh` call times out at 10s and prints a false "scan request failed". A cheaper check
settled it first: the call is guarded by `jellyfin_credentials()`, which needs *both*
`JELLYFIN_URL` and `JELLYFIN_API_KEY`. Neither is set in the environment or in any shell config, so
`request_jellyfin_scan()` has always taken its early return. The timeout has never been reached.

Graded **confirmed** for "unreachable as configured", and the underlying defect stays recorded for
anyone who does set those variables. Regraded in the report rather than deleted.

The general lesson, and it cost nothing: the question was "does this endpoint block?" and the
answer that mattered was "the call never happens". Checking the configuration was cheaper than
checking the server, and it was the check that actually settled it.

## The evaluation report now lives in the repo

`docs/archive/2026-09-04-evaluation-report.md`, linked from the README. It was in
`.engineering-team/runs/…`, which is gitignored — so the only record of 39 unfixed findings was one
`rm -rf` from gone. It carries a status header marking it point-in-time and listing what has since
been fixed or regraded; it is not a living document and should not be edited to match later code.

## What is deliberately not done

- **The remaining ~36 findings.** Next most useful, in order: F23/F24 (the fake-SSH harness routes
  on a bash *comment*, so rewording one fails 14 tests, while the playlist stdout assertions are
  containment-only and tolerate a stray `print`); F10 (a truncated playlist listing is
  indistinguishable from a short playlist and reports success — `| wc -l` discards yt-dlp's exit
  code); F28 ("Old file will be replaced" — nothing deletes it, so quality upgrades accumulate
  duplicates when a title changes).
- **F19, the mount guard.** Still not written, for the reason recorded last time: the mounts are
  `/mnt/nfs/movies` and `/mnt/nfs/downloads`, so the obvious `mountpoint -q /mnt/nfs` would fail on
  a healthy system every time. A correct version guards both leaf paths; nobody has been bitten yet.
- **`ssh.lines()`** is still dead code. Still not deleted — it is on the list, and removing it was
  not what this branch was for.
- **The duplicated download/stage logic across the three modes**, and the yt-dlp flag block copied
  across eight sites. A rewrite, not a repair.
