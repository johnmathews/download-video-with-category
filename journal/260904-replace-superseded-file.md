# 2026-09-04 — "Old file will be replaced" now replaces the old file

Fourth pass of the day; F28 from the evaluation.

## The bug

On a quality upgrade, `download_single()` printed:

```
✅ New quality is better - proceeding with download
   Old file will be replaced
```

and then nothing ever deleted anything. Replacement was incidental: it happened only when
rsync landed on a byte-identical filename. yt-dlp builds the name from the **current**
uploader and title (`-o "%(uploader)s-%(title)s-[%(id)s].%(ext)s"`), and YouTube titles get
edited routinely — so an upgrade usually arrives under a new name, rsync writes it alongside
the old one, and the category directory ends up with two files carrying the same `[id]`.

The next run's `find_existing()` uses `find … | head -1`, so which of the two it compares
against is whatever `find` happens to return first. Silent, and it accumulates.

## The fix

Record the decision (`superseded = existing`) rather than only announcing it, and after the
NAS transfer succeeds, `rm -f` the old path — but only when the new filenames genuinely
differ from it, since an unchanged name means rsync already overwrote it in place and
deleting would remove the file just downloaded.

Ordering is the whole safety argument, so it is worth stating: the delete happens **after**
the new file is in the library, never before. Every earlier exit — download failure, NAS
transfer failure, the refuse-to-guess path, the skip path — leaves the old file untouched.
Four of the six tests exist purely to pin that; they passed before the fix as well as after,
because their job is to catch the fix over-reaching rather than to demonstrate it working.

`_remove_superseded()` deliberately does not reuse `remove_remote()`. That helper is
`rm -rf … 2>/dev/null || true`, which is right for scratch directories and wrong for one of
the user's videos: no recursion, and a failure that is reported rather than swallowed. A
failed removal warns and leaves the run successful — the download did succeed, and the worst
case is the duplicate that existed before this change.

## Gotcha met

The first assertion was `f"rm -f {self.OLD}" in commands`, which failed while the code was
correct: the path contains `[brackets]`, so `q()` quotes it. Asserting on `q(self.OLD)` is
both correct and the more honest test — it checks the command that is actually sent.

## What is deliberately not done

- **Pre-existing duplicates are not cleaned up.** This stops new ones; it does not go looking
  for pairs already in the library. `find_existing()` returns one match (`head -1`), so a
  directory that already holds two copies of an id will shed one per future upgrade. A
  one-off sweep is a separate job and was not asked for.
- **No trash / undo.** The file is deleted, not moved aside. That is what the message has
  claimed since the zsh original; adding a holding area would be a new feature and a new
  place for things to accumulate.
- **F23/F24 remain** — the fake-SSH harness routes on a bash comment, and the playlist stdout
  assertions are containment-only. Next most useful item in
  `docs/archive/2026-09-04-evaluation-report.md`.
