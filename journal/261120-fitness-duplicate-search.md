# Fitness duplicate search no longer hides its errors

> Purpose: why `yt -f` now stops when it cannot search the show for an existing copy.

Follow-up to [261119-fail-early-unreadable-destination](261119-fail-early-unreadable-destination.md), which fixed
`single.find_existing()` and left `fitness._find_in_show()` for later.

## What was wrong

`_find_in_show()` ended `2>/dev/null | head -1`. The pipeline's exit status was head's, so a `find` that could not
read part of the show (one season directory with broken permissions, an NFS error mid-walk) and found nothing
came back as "not in this show". `yt -f` then downloaded the video again under the next episode number. The
destination preflight from 261119 covers the fitness base directory, not every season below it.

## Decision

Same contract as `single.find_existing()`: return the path, `''` for none, or `None` when the search failed
without a match. `-print -quit` replaces `| head -1`, find's stderr reaches the terminal, and `add_to_show`
stops with "Could not search … for an existing copy" and cleans up. A match still counts if find also hit an
error elsewhere. No `[ ! -e dir ] ||` guard as in single mode: `resolve()` has already created the show dir.

## Verified

Three tests run the generated command under a real `/bin/sh` against a temp show tree, including a season at
mode 000 (fails, `Permission denied` on stderr, no stdout). Disabling the new `None` check in `add_to_show` fails
the new caller test. Against the media VM: an existing episode in `Health` is found, an absent id gives `''`,
a missing show dir gives `None`. Full suite 243 passed, coverage 96.16%, ruff and pyright clean.
