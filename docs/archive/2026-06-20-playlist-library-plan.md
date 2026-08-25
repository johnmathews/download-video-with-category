**Status:** superseded by [architecture.md](../architecture.md) (2026-08-25). Historical plan/spec for the zsh implementation, which was ported to Python; kept for the design rationale.

# Playlist-as-Jellyfin-Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `yt -p <playlist-url>` mode that downloads a YouTube playlist, in order, into its own `/mnt/tank/movies/youtube/<slug>/` directory that becomes a manually-added Jellyfin movie library.

**Architecture:** A new `_yt_playlist_on_media_vm` function parallel to the existing single-video `_ytdl_on_media_vm` (Approach A). It uploads the cookie once, resolves+confirms a slug from the playlist title, then loops over playlist items one at a time — for each item, `yt-dlp --playlist-items N` downloads to `/tmp`, the existing two-stage SSD→HDD transfer runs to completion, then the next item begins. `--download-archive` makes re-runs cheap and gives free resume. The only shared extraction from the working single-video path is the stage-2 NAS rsync script.

**Tech Stack:** zsh 5.9, yt-dlp (remote, over SSH), rsync, bats 1.13 (tests run zsh subshells).

## Global Constraints

- zsh-only syntax (`zparseopts`, `${(@f)...}`, `${(ie)...}`, `setopt local_options pipefail`).
- All status/progress to **stderr**; only final NFS-visible file paths to **stdout** (one exception: the slug confirmation prompt, which reads the tty).
- SSH calls go through `$YT_SSH` (new var, defaults to `/usr/bin/ssh`) so tests can stub them; preserve `-o BatchMode=yes`.
- All variables embedded in remote SSH command strings are escaped with `printf '%q'`.
- Paths (verbatim from spec): final NFS view `/mnt/nfs/movies/youtube/<slug>/`; SSD staging `/mnt/nfs/downloads/yt-staging/<unique>/` (media view) = `/mnt/swift/downloads/yt-staging/<unique>/` (nas view); HDD final `/mnt/tank/movies/youtube/<slug>/`; archive at `/mnt/nfs/movies/youtube/<slug>/archive.txt`.
- Output filename template: `%(playlist_index)03d-%(title)s-[%(id)s].%(ext)s`.
- A failed item logs and continues; function returns non-zero iff any item failed.
- Tests must not contact the network or real hosts — `yt-dlp`/`ssh` are stubbed via `$YT_SSH`; `LOCAL_YT_COOKIES` points at a temp file.

---

### Task 1: `_yt_slugify` utility

**Files:**
- Modify: `yt.sh` (add function near the other helpers, before `yt()`)
- Test: `tests/slugify.bats` (create)

**Interfaces:**
- Produces: `_yt_slugify <text>` — prints an ASCII slug to stdout: lowercased, every run of non-`[a-z0-9]` collapsed to a single `-`, leading/trailing `-` trimmed. Empty input prints empty string.

- [ ] **Step 1: Write the failing tests**

Create `tests/slugify.bats`:

```bash
#!/usr/bin/env bats

setup() {
  cd "$BATS_TEST_DIRNAME/.."
}

slug() { run zsh -c "source ./yt.sh; _yt_slugify \"$1\""; }

@test "basic words to dashes" {
  slug "My Cooking Series"
  [ "$status" -eq 0 ]
  [ "$output" = "my-cooking-series" ]
}

@test "punctuation collapses to single dash" {
  slug "Hello, World! (2024)"
  [ "$output" = "hello-world-2024" ]
}

@test "leading and trailing junk trimmed" {
  slug "  /Trip — Italy/  "
  [ "$output" = "trip-italy" ]
}

@test "non-ascii becomes dashes" {
  slug "Café Música"
  [ "$output" = "caf-m-sica" ]
}

@test "empty input gives empty output" {
  slug ""
  [ "$output" = "" ]
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bats tests/slugify.bats`
Expected: FAIL — `_yt_slugify: command not found`.

- [ ] **Step 3: Implement `_yt_slugify`**

Add to `yt.sh` immediately before the `# Help text function` line:

```zsh
# Slugify a string for use as a directory name (lowercase ASCII, dashes).
_yt_slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bats tests/slugify.bats`
Expected: 5 passing.

- [ ] **Step 5: Commit**

```bash
git add yt.sh tests/slugify.bats
git commit -m "Add _yt_slugify helper with tests"
```

---

### Task 2: Extract shared NAS-transfer script + add `$YT_SSH` seam

**Files:**
- Modify: `yt.sh` (top-level constants near line 17; replace inline `nas_script` in `_ytdl_on_media_vm` ~`yt.sh:311-327`)
- Test: `tests/refactor_smoke.bats` (create)

**Interfaces:**
- Produces: top-level string constant `_YT_NAS_SCRIPT` (the stage-2 SSD→HDD rsync script body, identical to today's `nas_script`); top-level var `YT_SSH` defaulting to `/usr/bin/ssh`.
- Consumes (later tasks): `_YT_NAS_SCRIPT`, `$YT_SSH`.

This is a behavior-preserving refactor: the single-video path keeps identical logic, only sourcing the NAS script from a shared constant. `$YT_SSH` is introduced for the new playlist code; the single-video function is left calling `/usr/bin/ssh` directly to honor "don't disturb the proven path."

- [ ] **Step 1: Write the failing smoke test**

Create `tests/refactor_smoke.bats`:

```bash
#!/usr/bin/env bats

setup() { cd "$BATS_TEST_DIRNAME/.."; }

@test "YT_SSH defaults to /usr/bin/ssh" {
  run zsh -c 'source ./yt.sh; printf "%s" "$YT_SSH"'
  [ "$output" = "/usr/bin/ssh" ]
}

@test "shared NAS script constant is defined and rsyncs to final dir" {
  run zsh -c 'source ./yt.sh; printf "%s" "$_YT_NAS_SCRIPT"'
  [ "$status" -eq 0 ]
  [[ "$output" == *"rsync -rl --info=progress2 --remove-source-files"* ]]
}

@test "yt --help still works after refactor" {
  run zsh -c 'source ./yt.sh; yt --help'
  [ "$status" -eq 0 ]
  [[ "$output" == *"CATEGORIES:"* ]]
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bats tests/refactor_smoke.bats`
Expected: first two FAIL (`YT_SSH`/`_YT_NAS_SCRIPT` empty), third passes.

- [ ] **Step 3: Add the constants**

In `yt.sh`, after the `LOCAL_YT_COOKIES=...` line (~`yt.sh:17`), add:

```zsh
# SSH binary indirection so tests can stub remote calls. Defaults to the real ssh.
: ${YT_SSH:=/usr/bin/ssh}

# Stage-2 transfer script (NAS-local SSD swift -> HDD tank), shared by the
# single-video and playlist paths.
_YT_NAS_SCRIPT='
set -euo pipefail

staging_dir="$1"
final_dir="$2"

if [ ! -d "$staging_dir" ]; then
  echo "❌ Staging dir not found: $staging_dir" >&2
  exit 1
fi

mkdir -p "$final_dir"
rsync -rl --info=progress2 --remove-source-files "$staging_dir/" "$final_dir/" >&2
rmdir "$staging_dir" 2>/dev/null || true

echo "✅ Done." >&2
'
```

- [ ] **Step 4: Point the single-video path at the shared constant**

In `_ytdl_on_media_vm`, replace the inline `local nas_script='...'` block (the assignment spanning ~`yt.sh:311-327`) with:

```zsh
  local nas_script="$_YT_NAS_SCRIPT"
```

Leave the surrounding `/usr/bin/ssh ... <<<"$nas_script"` invocation unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `bats tests/refactor_smoke.bats`
Expected: 3 passing.

- [ ] **Step 6: Commit**

```bash
git add yt.sh tests/refactor_smoke.bats
git commit -m "Extract shared NAS-transfer script and add YT_SSH seam"
```

---

### Task 3: `_yt_playlist_on_media_vm` — cookie upload, slug confirm, per-item loop

**Files:**
- Modify: `yt.sh` (add function after `_ytdl_on_media_vm`, before `_yt_slugify`)
- Test: `tests/playlist.bats` (create)

**Interfaces:**
- Consumes: `$YT_SSH`, `_YT_NAS_SCRIPT`, `_yt_slugify`, `LOCAL_YT_COOKIES`, `REMOTE_FINAL_BASE`, `REMOTE_STAGING_BASE`, `NAS_STAGING_BASE`, `NAS_FINAL_BASE`, `NAS_SSH_HOST`.
- Produces: `_yt_playlist_on_media_vm <playlist-url>` — downloads the playlist; prints each final path `/mnt/nfs/movies/youtube/<slug>/<filename>` to stdout; prints summary `downloaded X, skipped Y, failed Z` to stderr; returns 0 iff `failed == 0`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/playlist.bats`:

```bash
#!/usr/bin/env bats

setup() {
  cd "$BATS_TEST_DIRNAME/.."
  STUB="$BATS_TEST_TMPDIR/ssh_stub.sh"
  LOG="$BATS_TEST_TMPDIR/calls.log"
  CK="$BATS_TEST_TMPDIR/cookies.txt"
  printf 'fake-cookie\n' > "$CK"
  cat > "$STUB" <<STUBEOF
#!/usr/bin/env bash
cmd="\$*"
echo "CMD: \$cmd" >> "$LOG"
if [ ! -t 0 ]; then cat > /dev/null; fi
case "\$cmd" in
  *"command -v yt-dlp"*) exit 0 ;;
  *"playlist_title"*) echo "Test Playlist"; exit 0 ;;
  *"playlist_index"*) echo "3"; exit 0 ;;
  *"mktemp -d"*) echo "/tmp/yt.stub.\$RANDOM"; exit 0 ;;
  *"umask 077"*) exit 0 ;;
  *"mkdir -p"*) exit 0 ;;
  *" nas "*) exit 0 ;;
  *"bash -s"*) echo "001-fake-[id].mkv"; exit 0 ;;
  *) exit 0 ;;
esac
STUBEOF
  chmod +x "$STUB"
}

run_pl() {
  # $1 = confirm input ; $2 = playlist url
  run zsh -c "source ./yt.sh; YT_SSH='$STUB'; LOCAL_YT_COOKIES='$CK'; _yt_playlist_on_media_vm '$2' <<< '$1'"
}

@test "downloads every item and reports success" {
  run_pl "y" "https://www.youtube.com/playlist?list=PLtest"
  [ "$status" -eq 0 ]
  [[ "$output" == *"downloaded 3, skipped 0, failed 0"* ]]
  # 3 media download calls (bash -s to media, i.e. not the nas calls)
  media_dl=$(grep "bash -s" "$LOG" | grep -vc " nas ")
  [ "$media_dl" -eq 3 ]
}

@test "emits final NFS paths to stdout under the slug dir" {
  run_pl "y" "https://www.youtube.com/playlist?list=PLtest"
  [[ "$output" == *"/mnt/nfs/movies/youtube/test-playlist/001-fake-[id].mkv"* ]]
}

@test "freeform answer overrides the slug" {
  run_pl "Holiday 2024!" "https://www.youtube.com/playlist?list=PLtest"
  [[ "$output" == *"/mnt/nfs/movies/youtube/holiday-2024/"* ]]
}

@test "n aborts before downloading" {
  run_pl "n" "https://www.youtube.com/playlist?list=PLtest"
  [ "$status" -ne 0 ]
  [ "$(grep -c "bash -s" "$LOG")" -eq 0 ]
}

@test "missing cookie file errors" {
  run zsh -c "source ./yt.sh; YT_SSH='$STUB'; LOCAL_YT_COOKIES='/nope/cookies.txt'; _yt_playlist_on_media_vm 'https://x/playlist?list=y' <<< 'y'"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Cookies file not found"* ]]
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bats tests/playlist.bats`
Expected: FAIL — `_yt_playlist_on_media_vm: command not found` (except possibly the missing-cookie case).

- [ ] **Step 3: Implement the function**

Add to `yt.sh` immediately after the closing `}` of `_ytdl_on_media_vm` (~`yt.sh:353`):

```zsh
# Per-item playlist download script (stage 1): yt-dlp one playlist item to
# $tmpdir, then rsync to SSD staging. stdout = video basenames (skip => empty).
_YT_PLAYLIST_ITEM_SCRIPT='
set -euo pipefail

tmpdir="$1"
cookie="$2"
staging_dir="$3"
url="$4"
item="$5"
archive="$6"

mkdir -p "$staging_dir"

yt-dlp \
  --remote-components ejs:github \
  --cookies "$cookie" \
  --download-archive "$archive" \
  --playlist-items "$item" \
  --embed-metadata \
  --embed-chapters \
  --embed-thumbnail \
  --convert-thumbnails jpg \
  --sub-langs "en.*" \
  --write-subs \
  --write-auto-subs \
  --embed-subs \
  --convert-subs srt \
  --sub-format "srv3/ttml/vtt/best" \
  --sleep-subtitles 1 \
  -f bestvideo+bestaudio \
  --merge-output-format mkv \
  --restrict-filenames \
  -o "$tmpdir/%(playlist_index)03d-%(title)s-[%(id)s].%(ext)s" \
  "$url" >&2 || true

shopt -s nullglob
video_files=("$tmpdir"/*.{mkv,mp4})
if (( ${#video_files[@]} == 0 )); then
  # Either already in the archive (skip) or a subtitle abort. Retry without
  # subs; a true skip still produces no file and is handled below.
  yt-dlp \
    --remote-components ejs:github \
    --cookies "$cookie" \
    --download-archive "$archive" \
    --playlist-items "$item" \
    --embed-metadata \
    --embed-chapters \
    --embed-thumbnail \
    --convert-thumbnails jpg \
    -f bestvideo+bestaudio \
    --merge-output-format mkv \
    --restrict-filenames \
    -o "$tmpdir/%(playlist_index)03d-%(title)s-[%(id)s].%(ext)s" \
    "$url" >&2 || true
  video_files=("$tmpdir"/*.{mkv,mp4})
fi

# Drop sidecars (embedded in mkv; loose images confuse Jellyfin poster scan).
rm -f "$tmpdir"/*.{jpg,jpeg,png,webp,srt,vtt} 2>/dev/null || true

if (( ${#video_files[@]} == 0 )); then
  # Nothing downloaded -> already archived. Clean up, emit nothing (skip).
  rmdir "$tmpdir" 2>/dev/null || rm -rf "$tmpdir"
  exit 0
fi

files=("$tmpdir"/*.{mkv,mp4,json,nfo} "$tmpdir"/*info.json)
rsync --info=progress2 --remove-source-files "${files[@]}" "$staging_dir/" >&2
for f in "${files[@]}"; do
  case "$f" in
    *.mkv|*.mp4) echo "$(basename "$f")" ;;
  esac
done
rmdir "$tmpdir" 2>/dev/null || rm -rf "$tmpdir"
'

# Download an entire playlist into its own Jellyfin movie library directory.
_yt_playlist_on_media_vm() {
  setopt local_options pipefail

  local _yt_start=$SECONDS
  _yt_elapsed() {
    local secs=$(( SECONDS - _yt_start ))
    if (( secs >= 60 )); then
      printf '%dm %ds' $((secs / 60)) $((secs % 60))
    else
      printf '%ds' $secs
    fi
  }

  local url="$1"
  if [[ -z "$url" ]]; then
    echo "Usage: ${funcstack[1]} <playlist-url>" >&2
    return 1
  fi

  # Cookie validation (mirrors single-video path).
  if [[ ! -f "$LOCAL_YT_COOKIES" ]]; then
    echo "❌ Cookies file not found:" >&2
    echo "   $LOCAL_YT_COOKIES" >&2
    return 1
  fi
  if [[ ! -s "$LOCAL_YT_COOKIES" ]]; then
    echo "❌ Cookies file is empty: $LOCAL_YT_COOKIES" >&2
    return 1
  fi
  local cookie_age_days=$(( ($(date +%s) - $(stat -f %m "$LOCAL_YT_COOKIES" 2>/dev/null || stat -c %Y "$LOCAL_YT_COOKIES")) / 86400 ))
  if [[ $cookie_age_days -gt 7 ]]; then
    echo "⚠️  Warning: Cookies file is $cookie_age_days days old (may be stale)" >&2
  fi

  if ! $YT_SSH -o BatchMode=yes media 'command -v yt-dlp >/dev/null 2>&1'; then
    echo "❌ yt-dlp not found on media VM" >&2
    return 1
  fi

  # Upload cookie once into a dedicated remote tmp dir.
  local remote_cookie_dir
  remote_cookie_dir="$($YT_SSH -o BatchMode=yes media 'mktemp -d /tmp/yt.pl.XXXXXX')" || {
    echo "❌ Failed to create remote temp dir" >&2
    return 1
  }
  local _q_cookie_dir=$(printf '%q' "$remote_cookie_dir")
  trap "$YT_SSH media \"rm -rf $_q_cookie_dir 2>/dev/null || true\" 2>/dev/null; trap - INT TERM; return 130" INT TERM

  local remote_cookie="$remote_cookie_dir/cookies.txt"
  echo "🍪 [$(_yt_elapsed)] Copying cookies to media VM..." >&2
  $YT_SSH media "umask 077 && cat > $(printf '%q' "$remote_cookie")" < "$LOCAL_YT_COOKIES" || {
    echo "❌ Failed to copy cookies to media VM" >&2
    $YT_SSH media "rm -rf $_q_cookie_dir 2>/dev/null || true"
    trap - INT TERM
    return 1
  }

  # Resolve the playlist title -> slug, confirm/override.
  echo "🔍 [$(_yt_elapsed)] Fetching playlist title..." >&2
  local playlist_title
  playlist_title="$($YT_SSH -o BatchMode=yes media "yt-dlp --remote-components ejs:github --flat-playlist --playlist-items 1 --print '%(playlist_title)s' --cookies $(printf '%q' "$remote_cookie") $(printf '%q' "$url") 2>/dev/null" || echo "")"

  local suggested
  suggested="$(_yt_slugify "$playlist_title")"
  [[ -z "$suggested" ]] && suggested="playlist"

  printf "Use directory '%s'? [Y/n/edit]: " "$suggested" >&2
  local answer slug
  read -r answer
  case "$answer" in
    ""|y|Y) slug="$suggested" ;;
    n|N)
      echo "Aborted — nothing downloaded." >&2
      $YT_SSH media "rm -rf $_q_cookie_dir 2>/dev/null || true"
      trap - INT TERM
      return 1
      ;;
    *)
      slug="$(_yt_slugify "$answer")"
      if [[ -z "$slug" ]]; then
        echo "❌ '$answer' slugifies to an empty name" >&2
        $YT_SSH media "rm -rf $_q_cookie_dir 2>/dev/null || true"
        trap - INT TERM
        return 1
      fi
      ;;
  esac

  local final_remote_dir="${REMOTE_FINAL_BASE}/${slug}"
  local nas_final_dir="${NAS_FINAL_BASE}/${slug}"
  local archive_remote="${final_remote_dir}/archive.txt"

  $YT_SSH -o BatchMode=yes media "mkdir -p $(printf '%q' "$final_remote_dir")" || {
    echo "❌ Could not create $final_remote_dir on media VM" >&2
    $YT_SSH media "rm -rf $_q_cookie_dir 2>/dev/null || true"
    trap - INT TERM
    return 1
  }

  # Count playlist items.
  local count
  count="$($YT_SSH -o BatchMode=yes media "yt-dlp --remote-components ejs:github --flat-playlist --print '%(playlist_index)s' --cookies $(printf '%q' "$remote_cookie") $(printf '%q' "$url") 2>/dev/null | wc -l" | tr -d '[:space:]')"
  if [[ -z "$count" || "$count" == "0" ]]; then
    echo "❌ Playlist is empty or could not be read" >&2
    $YT_SSH media "rm -rf $_q_cookie_dir 2>/dev/null || true"
    trap - INT TERM
    return 1
  fi

  echo "" >&2
  echo "📚 Playlist: $playlist_title" >&2
  echo "📁 Library dir: $final_remote_dir  ($count items)" >&2
  echo "" >&2

  local downloaded=0 skipped=0 failed=0 n
  for (( n = 1; n <= count; n++ )); do
    echo "▶️  [$(_yt_elapsed)] [$n/$count] processing item $n..." >&2

    local item_tmpdir staging_subdir item_staging
    item_tmpdir="$($YT_SSH -o BatchMode=yes media 'mktemp -d /tmp/yt.XXXXXX')" || {
      echo "❌ [$n/$count] mktemp failed" >&2
      (( failed++ ))
      continue
    }
    staging_subdir="$(basename "$item_tmpdir")"
    item_staging="${REMOTE_STAGING_BASE}/${staging_subdir}"

    # Stage 1: download item + rsync to SSD staging.
    local basenames
    if ! basenames="$($YT_SSH -o BatchMode=yes media "bash -s -- $(printf '%q' "$item_tmpdir") $(printf '%q' "$remote_cookie") $(printf '%q' "$item_staging") $(printf '%q' "$url") $(printf '%q' "$n") $(printf '%q' "$archive_remote")" <<<"$_YT_PLAYLIST_ITEM_SCRIPT")"; then
      echo "❌ [$n/$count] download/staging failed" >&2
      $YT_SSH media "rm -rf $(printf '%q' "$item_tmpdir") $(printf '%q' "$item_staging") 2>/dev/null || true"
      (( failed++ ))
      continue
    fi

    if [[ -z "$basenames" ]]; then
      echo "⏭️  [$n/$count] already downloaded — skipped" >&2
      (( skipped++ ))
      continue
    fi

    # Stage 2: NAS-local SSD -> HDD into the playlist library dir.
    local nas_staging="${NAS_STAGING_BASE}/${staging_subdir}"
    if $YT_SSH -o BatchMode=yes "$NAS_SSH_HOST" "bash -s -- $(printf '%q' "$nas_staging") $(printf '%q' "$nas_final_dir")" <<<"$_YT_NAS_SCRIPT"; then
      (( downloaded++ ))
      local line
      for line in "${(@f)basenames}"; do
        [[ -n "$line" ]] && echo "${final_remote_dir}/${line}"
      done
    else
      echo "❌ [$n/$count] NAS transfer failed — files remain on SSD: $nas_staging" >&2
      (( failed++ ))
    fi
  done

  # Cleanup cookie dir.
  $YT_SSH media "rm -rf $_q_cookie_dir 2>/dev/null || true"
  trap - INT TERM

  echo "" >&2
  echo "✅ [$(_yt_elapsed)] Playlist '$slug': downloaded $downloaded, skipped $skipped, failed $failed" >&2
  (( failed == 0 ))
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bats tests/playlist.bats`
Expected: 5 passing.

- [ ] **Step 5: Commit**

```bash
git add yt.sh tests/playlist.bats
git commit -m "Add _yt_playlist_on_media_vm with per-item streaming loop"
```

---

### Task 4: Wire `-p` / `--playlist` into `yt()`

**Files:**
- Modify: `yt.sh` — `zparseopts` call (~`yt.sh:429`) and the dispatch logic after it
- Test: `tests/flags.bats` (create)

**Interfaces:**
- Consumes: `_yt_playlist_on_media_vm`.
- Produces: `yt -p <url>` / `yt --playlist <url>` dispatch; error if combined with any category flag or `--category`; error if URL missing.

- [ ] **Step 1: Write the failing tests**

Create `tests/flags.bats`:

```bash
#!/usr/bin/env bats

setup() {
  cd "$BATS_TEST_DIRNAME/.."
  # Stub the playlist worker so dispatch tests never hit ssh.
  PRELUDE='source ./yt.sh; _yt_playlist_on_media_vm() { echo "PLAYLIST_CALLED url=$1"; }'
}

@test "-p with a category flag is rejected" {
  run zsh -c "$PRELUDE; yt -p -t 'https://youtube.com/playlist?list=x'"
  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot be combined"* ]]
}

@test "-p with no URL errors" {
  run zsh -c "$PRELUDE; yt -p"
  [ "$status" -ne 0 ]
  [[ "$output" == *"playlist URL is required"* ]]
}

@test "-p dispatches to the playlist worker with the URL" {
  run zsh -c "$PRELUDE; yt -p 'https://youtube.com/playlist?list=x'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PLAYLIST_CALLED url=https://youtube.com/playlist?list=x"* ]]
}

@test "--playlist long form also dispatches" {
  run zsh -c "$PRELUDE; yt --playlist 'https://youtube.com/playlist?list=x'"
  [[ "$output" == *"PLAYLIST_CALLED"* ]]
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bats tests/flags.bats`
Expected: FAIL — `-p` is not yet a recognized flag (zparseopts leaves it as a positional, so it lands in `url` and no playlist dispatch happens).

- [ ] **Step 3: Add `p` and `--playlist` to zparseopts**

In `yt()`, change the parse line (`yt.sh:429`) to:

```zsh
  zparseopts -D -E -A opts -- g y c m h t e p -category: -help -update -playlist
```

- [ ] **Step 4: Add the playlist dispatch branch**

In `yt()`, immediately after the `--update` handling block (after the `fi` that closes the `if (( ${+opts[--update]} ))` at ~`yt.sh:436`), insert:

```zsh
  # Playlist mode: download a whole playlist into its own library dir.
  if (( ${+opts[-p]} || ${+opts[--playlist]} )); then
    if (( ${+opts[-g]} || ${+opts[-y]} || ${+opts[-c]} || ${+opts[-m]} || ${+opts[-h]} || ${+opts[-t]} || ${+opts[-e]} )) || [[ -n "${opts[--category]}" ]]; then
      echo "❌ Error: -p/--playlist cannot be combined with a category flag" >&2
      return 1
    fi
    local playlist_url="$1"
    if [[ -z "$playlist_url" ]]; then
      echo "❌ Error: playlist URL is required" >&2
      echo "Usage: yt -p <playlist-url>" >&2
      return 1
    fi
    noglob _yt_playlist_on_media_vm "$playlist_url"
    return $?
  fi
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `bats tests/flags.bats`
Expected: 4 passing.

- [ ] **Step 6: Run the whole suite**

Run: `bats tests/`
Expected: all tasks' tests pass (slugify 5, refactor 3, playlist 5, flags 4).

- [ ] **Step 7: Commit**

```bash
git add yt.sh tests/flags.bats
git commit -m "Wire -p/--playlist flag into yt() dispatch"
```

---

### Task 5: Documentation & journal

**Files:**
- Modify: `readme.md`, `_yt_show_help` in `yt.sh` (~`yt.sh:356-412`), `CLAUDE.md`
- Create: `journal/260620-playlist-library.md`

- [ ] **Step 1: Update `_yt_show_help`**

In the `OPTIONS:` section of the heredoc, add after the `--category` line:

```
  -p, --playlist URL     Download an entire playlist into its own library dir
```

In `EXAMPLES:`, add:

```
  Download a playlist as its own Jellyfin library:
    yt -p "https://www.youtube.com/playlist?list=PLxxxxxxxx"
```

In `FILES:`, add:

```
  Playlists are saved to:    /mnt/nfs/movies/youtube/{PLAYLIST-SLUG}/
```

- [ ] **Step 2: Update `readme.md`**

Add a "Playlists" section documenting: `yt -p <url>`, the slug confirm/override prompt, that each playlist becomes its own directory under `/mnt/tank/movies/youtube/` to be added manually as a Jellyfin movie library, the `001-`-prefixed ordering, and `--download-archive` resume/re-run behavior. (Match the file's existing tone/structure — read it first.)

- [ ] **Step 3: Update `CLAUDE.md`**

Under "Architecture" / function list, add `_yt_playlist_on_media_vm()` (per-item streaming playlist download) and note the shared `_YT_NAS_SCRIPT` constant and `$YT_SSH` test seam. In "Adding a New Category", note that playlists are a separate path and don't use `valid_categories`. Add a short "Testing" note: `bats tests/`.

- [ ] **Step 4: Write the journal entry**

Create `journal/260620-playlist-library.md` capturing: the goal, Approach A and why (don't disturb the single-video path), the five brainstorming decisions (auto-slug-with-confirm, manual Jellyfin lib, download-archive, per-video streaming, flat indexed movie lib), and the test approach (bats + `$YT_SSH` stub).

- [ ] **Step 5: Verify and commit**

Run: `bats tests/` (confirm still green) and `zsh -c 'source ./yt.sh; yt --help'` (confirm `-p` shows).

```bash
git add readme.md yt.sh CLAUDE.md journal/260620-playlist-library.md
git commit -m "Document playlist download feature"
```

---

## Self-Review

**Spec coverage:** invocation/flag + slug-with-override → Tasks 1,4 + Task 3 prompt; manual Jellyfin lib → docs only (no code, correct); download-archive resume → Task 3 item script; per-video sequential streaming → Task 3 loop; flat indexed movie lib → output template in Task 3; Approach A + shared transfer helper → Task 2; error-continue + summary + exit code → Task 3; output contract → Task 3 stdout emission; tests → every task; docs/journal → Task 5. All covered.

**Placeholder scan:** no TBD/TODO; all code blocks complete; doc-prose steps (readme/journal) are content specs, not code placeholders.

**Type/name consistency:** `_yt_slugify`, `_YT_NAS_SCRIPT`, `_YT_PLAYLIST_ITEM_SCRIPT`, `_yt_playlist_on_media_vm`, `YT_SSH` used consistently across tasks; the item script's 6 positional args ($tmpdir,$cookie,$staging_dir,$url,$item,$archive) match the `bash -s --` call order in the loop; `_YT_NAS_SCRIPT`'s 2 args ($staging_dir,$final_dir) match both call sites.
