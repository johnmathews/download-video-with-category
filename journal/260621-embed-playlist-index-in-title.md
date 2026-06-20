# Embed playlist index into title metadata

**Date:** 2026-06-21

## Context

The playlist feature already prefixes filenames with the 3-digit playlist
position (`001-...`). But Jellyfin's display **Name** (which drives its default
sort) can come from the *embedded title metadata* rather than the filename —
specifically when the library setting **"Prefer embedded titles over
filenames"** is enabled. In that case the un-prefixed embedded title would sort
out of playlist order.

## Change

Added `--parse-metadata "%(playlist_index)03d - %(title)s:%(meta_title)s"` to
both yt-dlp invocations in `_YT_PLAYLIST_ITEM_SCRIPT` (main + no-subs retry).
yt-dlp's `meta_title` field overrides the title tag written by
`--embed-metadata`, so the embedded title becomes e.g. `001 - Original Title`
while `%(title)s` (used in the filename) is untouched. Now both the filename and
the embedded title carry the index, so ordering holds regardless of which one
Jellyfin uses.

## Notes / caveats

- Default Jellyfin behaviour uses the filename for the Name, so this is
  belt-and-suspenders for users who enable "Prefer embedded titles over
  filenames".
- The embedded prefix only applies to files downloaded after this change;
  pre-existing playlists (e.g. `heavy-club-*`) have un-prefixed embedded titles.
- Changing the Jellyfin setting requires a **"Replace all metadata"** library
  refresh to re-derive the stored Name — a plain file scan won't re-evaluate
  unchanged files.
- Padding is `03d` → correct lexical sort up to 999 items.

## Tests

Added a structural assertion in `tests/playlist.bats` that both yt-dlp calls in
the item script carry the `--parse-metadata` flag (the fake yt-dlp used in the
direct item-script tests doesn't process metadata, so effect-level verification
needs a real download + `ffprobe`). Full suite: 24/24.
