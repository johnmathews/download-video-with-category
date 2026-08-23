# 2026-08-23 — `yt -f`: add a video to a show/season of the Jellyfin Health & Fitness library

**Why.** The flat per-playlist Jellyfin movie libraries were replaced by one *Shows* library
(show = subgenre, season = sub-subgenre; see proxmox-setup
`documentation/jellyfin_health_fitness_library.md`). Until now a new fitness video needed a
manual rename to `<Show> SnnEnn - …-[id].mkv`, a hand-written `.nfo` and a thumbnail.

**What landed.**
- `yt -f [Show/Season] URL`. With just a URL it asks: which show (numbered list + new), which
  season (numbered with episode counts + new), confirm. Plain `input`-style prompts like `gm`.
  `Show/3`, `Show/Name`, `Show/N:Name` (create) are the no-questions fast path.
- Media-VM scripts: list (`season.nfo` titles, counts), resolve (season dir + next episode,
  creates show/season with nfo on `N:Name`), item (download with `--write-info-json
  --write-thumbnail`, rename every sidecar to the `SnnEnn` prefix, stage to SSD).
- `jellyfin_nfo.py`: stdlib-only, piped to the media VM's python3; writes the episode nfo (title,
  cleaned description `Channel · date` + first real paragraph, aired, sort title, uniqueid) and
  renames the thumb; deletes info.json. Cleaner copied from proxmox-setup `migrate.py`.
- Duplicate check by YouTube id across the whole show; optional Jellyfin scan via
  `JELLYFIN_URL`/`JELLYFIN_API_KEY`; reminder to run `make_posters.py` for a new season.
- Tests: `tests/fitness.bats` (8) + `tests/jellyfin_nfo.bats` (3); whole suite 35/35.

**Gotchas met.** zsh keeps the quotes in `assoc["k"]` as part of the key; `|` inside
`${x%%|*}` is a glob alternation; `printf %q` escapes the space in `Season 03` (tests grep for
`fitness/Kettlebell/Season`). An earlier draft had an unescaped `"<Show>/<Season>"` inside an
`echo "…"` — zsh parses `<Show>` as a redirect — caught by the patch anchor failing.

**First live run (same day).** The show list came back empty: the listing script's last
statement was `[ $any = 0 ] && printf …`, which leaves bash's exit status at 1 whenever the last
show has seasons, so `ssh` returned 1 and `|| listing=""` discarded the output. Now `exit 0`
explicitly, and yt.sh keeps whatever was listed regardless of the exit code (warns if empty).
Also `season.nfo` titles are XML-escaped (`Mobility &amp; Physio`) — unescaped when listing and
matching, escaped when writing new nfo.

**Newest-first.** John wants feed-style seasons sorted newest first; Jellyfin has no descending
option for episodes. Implemented "feed" seasons numbered down from 999 (course seasons stay
1..N), an `.order` marker per season dir, prompts for it (new season: default feed; existing
season without a marker: asked once), `--season-order`, and `Show/N:Name:feed|course` inline.
The one-off renumber of the existing loose seasons lives in proxmox-setup (`reorder-season`).
Second exit-status trap of the day: the picker ended with `[[ -n … ]] && printf`, returning 1
when there was nothing to print, which read as "aborted".

**First successful real run.** `yt -f` → Mobility & Physio S01E983 (feed: newest first), nfo title /
plot / aired written, Jellyfin indexed it with the nfo title, overview and thumbnail on the next scan.
Two things found: the media VM's apt/PPA yt-dlp (2026.03.17) 403'd mid-download — replaced by the
official standalone binary (proxmox-setup media_vm role, `yt --update`); leftover `.srv3` subtitle
sidecars are now removed (subs are embedded). Thumbnail may stay `.webp` when the first attempt
succeeds — Jellyfin reads webp fine.
