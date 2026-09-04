# 2026-09-04 — A truncated playlist listing no longer reports success

Third pass of the day, working the next item off the evaluation's deferred list (F10).

## The bug

`_playlist_count()` asked the media VM for the playlist's length like this:

```
yt-dlp --flat-playlist --print '%(playlist_index)s' … 2>/dev/null | wc -l
```

A pipeline's exit status is the **last** command's. `wc -l` essentially always succeeds, so
`result.returncode` was 0 no matter what yt-dlp did, and `2>/dev/null` threw away the reason. If
yt-dlp died partway through a 200-item listing — network blip, throttling, stale cookie — `count`
became 50, the loop downloaded 50 items, and the run finished with
`✅ Playlist 'x': downloaded 50, skipped 0, failed 0` and exit 0. Nothing anywhere said the library
was incomplete.

The `count == 0` guard did not help: it only catches a listing that produced *nothing*.

Confirmed against live yt-dlp, old form versus new, on a nonexistent playlist:

```
old (piped):    exit=0   "0"                     <- reported success
new (no pipe):  exit=1   stderr: HTTP Error 404
new (real 19-item playlist): exit=0, 19 lines
```

**Grading, because the two cases differ.** That 404 was *already* caught by `count == 0` — it is
evidence that the exit code now propagates, not that this specific input was broken before. The
case actually fixed is the **partial** listing, which I could not reproduce on demand. Confirmed:
the exit status now reaches Python. Strongly supported: a partial listing therefore aborts rather
than silently downloading a prefix.

## The fix

Drop the pipe, count the printed lines in Python, and return `None` — not `0` — when yt-dlp
failed, so the caller can tell "empty playlist" from "could not read it". Those two now print
different messages; previously one message covered both and was wrong about which had happened.

`2>/dev/null` is gone too. yt-dlp's stderr goes to the terminal like every other remote progress
line, so a failure says *why* (`HTTP Error 404`, an expired cookie, and so on) instead of vanishing.
That is the change with the most day-to-day value: the old code hid the diagnosis of the very
failure it then mishandled.

## Gotcha met

The test fake for the count call returned `"3\n"` and, for the empty case, `"0\n"` — it was
modelling the output of `wc -l`, not of yt-dlp. Removing the pipe changed the contract, so both
fakes had to change (`"1\n2\n3\n"`, and `""` for empty). Worth noticing rather than fixing on
autopilot: a fake that encodes a *pipeline's* semantics rather than the *command's* is exactly how
a test keeps passing while the thing under it changes meaning. `test_the_count_command_is_not_piped`
now pins the shape directly, so reintroducing the pipe fails a test by name rather than only
showing up as a mysteriously short playlist.

## What is deliberately not done

- **No retry on a failed listing.** Aborting with a clear message is the right default; a retry
  policy is a bigger decision and nobody has asked for one.
- **The per-item loop still trusts `count`.** If yt-dlp lists 200 and item 137 is later deleted,
  that item fails and is counted as failed — which is correct and already handled.
- **F23/F24 and F28 remain**, still the next most useful items in
  `docs/archive/2026-09-04-evaluation-report.md`.
