#!/usr/bin/env zsh
# ---- youtube download -> media vm (server-side) ----
#
# All informational output goes to stderr.
# On success, stdout emits the final file path (for piping to epm, etc).

# Where the media VM should place final files (NFS mount already available there)
REMOTE_FINAL_BASE="/mnt/nfs/movies/youtube"

# Two-stage SSD-staged transfer: media VM → SSD NFS → HDD (NAS-local copy)
REMOTE_STAGING_BASE="/mnt/nfs/downloads/yt-staging"  # SSD NFS as seen from media VM
NAS_STAGING_BASE="/mnt/swift/downloads/yt-staging"    # Same dir as seen from NAS locally
NAS_FINAL_BASE="/mnt/tank/movies/youtube"             # HDD as seen from NAS locally
NAS_SSH_HOST="nas"

# Local cookies file on your Mac (Netscape cookies.txt format)
LOCAL_YT_COOKIES="$HOME/.config/yt-dlp/cookies/cookies.txt"

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

_ytdl_on_media_vm() {
  setopt local_options pipefail

  local _yt_start=$SECONDS

  # Format elapsed time as human-readable string (e.g. "1m 23s", "45s")
  _yt_elapsed() {
    local secs=$(( SECONDS - _yt_start ))
    if (( secs >= 60 )); then
      printf '%dm %ds' $((secs / 60)) $((secs % 60))
    else
      printf '%ds' $secs
    fi
  }

  local category="$1"   # e.g. youtube, gym, create, music
  local url="$2"

  if [[ -z "$category" || -z "$url" ]]; then
    # shellcheck disable=SC2154  # funcstack is a zsh built-in array
    echo "Usage: ${funcstack[1]} <category> <url>" >&2
    return 1
  fi

  # Validate URL format (basic check for supported video sites)
  if [[ ! "$url" =~ ^https?://(www\.)?(youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|twitch\.tv) ]]; then
    echo "⚠️  Warning: URL doesn't look like a supported video site" >&2
    echo "   Supported: YouTube, Vimeo, Dailymotion, Twitch" >&2
    echo "   Proceeding anyway..." >&2
  fi

  # Check cookies file exists and has content
  if [[ ! -f "$LOCAL_YT_COOKIES" ]]; then
    echo "❌ Cookies file not found:" >&2
    echo "   $LOCAL_YT_COOKIES" >&2
    echo "Export youtube.com cookies to this file (Netscape cookies.txt)." >&2
    return 1
  fi

  if [[ ! -s "$LOCAL_YT_COOKIES" ]]; then
    echo "❌ Cookies file is empty:" >&2
    echo "   $LOCAL_YT_COOKIES" >&2
    return 1
  fi

  # Warn if cookies are older than 7 days (likely stale)
  local cookie_age_days=$(( ($(date +%s) - $(stat -f %m "$LOCAL_YT_COOKIES" 2>/dev/null || stat -c %Y "$LOCAL_YT_COOKIES")) / 86400 ))
  if [[ $cookie_age_days -gt 7 ]]; then
    echo "⚠️  Warning: Cookies file is $cookie_age_days days old (may be stale)" >&2
    echo "   Consider re-exporting fresh cookies from your browser" >&2
  fi

  # Check if yt-dlp is installed on remote
  if ! /usr/bin/ssh -o BatchMode=yes media 'command -v yt-dlp >/dev/null 2>&1'; then
    echo "❌ yt-dlp not found on media VM" >&2
    echo "   Install it with: ssh media 'pip install yt-dlp'" >&2
    return 1
  fi

  # Remote temp paths
  local remote_tmpdir
  remote_tmpdir="$(/usr/bin/ssh -o BatchMode=yes media 'mktemp -d /tmp/yt.XXXXXX')" || {
    echo "❌ Failed to create remote temp dir" >&2
    return 1
  }

  # Pre-escape for safe embedding in SSH commands and trap strings
  local _q_tmpdir=$(printf '%q' "$remote_tmpdir")

  # Derive a unique SSD staging subdir from the tmpdir basename (e.g. yt.a1b2c3)
  local staging_subdir="$(basename "$remote_tmpdir")"
  local remote_staging_dir="${REMOTE_STAGING_BASE}/${staging_subdir}"
  local _q_staging_dir=$(printf '%q' "$remote_staging_dir")

  # Setup cleanup trap to ensure temp files are removed even on interrupt
  trap "/usr/bin/ssh media \"rm -rf $_q_tmpdir $_q_staging_dir 2>/dev/null || true\" 2>/dev/null; trap - INT TERM; return 130" INT TERM

  # Put cookie inside tempdir to avoid collisions
  local remote_cookie="$remote_tmpdir/cookies.txt"

  # Upload cookies (atomic with restrictive permissions to avoid permission window)
  echo "🍪 [$(_yt_elapsed)] Copying cookies to media VM..." >&2
  /usr/bin/ssh media "umask 077 && cat > $(printf '%q' "$remote_cookie")" < "$LOCAL_YT_COOKIES" || {
    echo "❌ Failed to copy cookies to media VM" >&2
    /usr/bin/ssh media "rm -rf $_q_tmpdir 2>/dev/null || true"
    return 1
  }

  # Build remote final dir
  local remote_final_dir="${REMOTE_FINAL_BASE}/${category}"

  echo "⏬ Downloading on media VM to: $remote_tmpdir" >&2
  echo "📦 Staging via SSD: $remote_staging_dir" >&2
  echo "📦 Final destination: $remote_final_dir" >&2
  echo "" >&2

  # Fetch video info for display and duplicate checking
  echo "🔍 [$(_yt_elapsed)] Fetching video info..." >&2
  local video_info
  video_info="$(/usr/bin/ssh -o BatchMode=yes media "yt-dlp --remote-components ejs:github --print '%(id)s' --print '%(title)s' --print '%(height)sp' --print '%(filesize_approx)s' --cookies $(printf '%q' "$remote_cookie") $(printf '%q' "$url") 2>/dev/null" || printf 'unknown\nUnknown Video\n0p\n0')"

  local -a info_lines=("${(@f)video_info}")
  local video_id="${info_lines[1]}"
  local video_title="${info_lines[2]}"
  local new_quality="${info_lines[3]}"
  local filesize_bytes="${info_lines[4]}"

  if [[ "$video_id" == "unknown" ]]; then
    echo "⚠️  Warning: Could not fetch video info — yt-dlp may be outdated" >&2
    echo "   Run 'yt --update' to update yt-dlp on the media VM" >&2
    echo "" >&2
  fi

  # Format filesize with smart rounding
  local filesize_display="Unknown"
  if [[ "$filesize_bytes" =~ ^[0-9]+$ && "$filesize_bytes" != "0" ]]; then
    local size_mb=$((filesize_bytes / 1048576))  # Convert to MB
    if [[ $size_mb -lt 1024 ]]; then
      # Less than 1 GB - show in MB
      if [[ $size_mb -ge 100 ]]; then
        # Round to nearest 10 for large MB values
        size_mb=$(( (size_mb + 5) / 10 * 10 ))
        filesize_display="${size_mb} MB"
      else
        # Show 1 decimal place for smaller values
        local size_mb_decimal=$(awk "BEGIN {printf \"%.1f\", $filesize_bytes / 1048576}")
        filesize_display="${size_mb_decimal} MB"
      fi
    else
      # 1 GB or more - show in GB with 1 decimal
      local size_gb=$(awk "BEGIN {printf \"%.1f\", $filesize_bytes / 1073741824}")
      filesize_display="${size_gb} GB"
    fi
  fi

  echo "" >&2
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
  echo "📹 VIDEO: $video_title" >&2
  echo "🆔 ID: $video_id" >&2
  echo "📊 Quality: $new_quality" >&2
  echo "📦 Size: ~$filesize_display" >&2
  echo "📁 Category: $category" >&2
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
  echo "" >&2

  # Check if video already exists
  echo "🔎 [$(_yt_elapsed)] Checking for existing downloads..." >&2
  local existing_file
  existing_file="$(/usr/bin/ssh -o BatchMode=yes media "find $(printf '%q' "$remote_final_dir") -type f -name '*\\[${video_id}\\]*' 2>/dev/null | head -1" || echo "")"

  if [[ -n "$existing_file" ]]; then
    echo "⚠️  Found existing file: $(basename "$existing_file")" >&2

    # Get quality of existing file using ffprobe
    local existing_quality
    existing_quality="$(/usr/bin/ssh -o BatchMode=yes media "ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 $(printf '%q' "$existing_file") 2>/dev/null" || echo "0")"
    existing_quality="${existing_quality}p"

    echo "   Existing quality: $existing_quality" >&2
    echo "   New quality: $new_quality" >&2

    # Compare qualities (extract numeric values)
    local existing_num="${existing_quality%p}"
    local new_num="${new_quality%p}"

    if [[ "$new_num" -le "$existing_num" ]]; then
      echo "" >&2
      echo "❌ Skipping download - existing file has equal or better quality" >&2
      echo "   To force re-download, delete: $existing_file" >&2
      # Emit existing path to stdout so piping (e.g. yt ... | epm) still works
      echo "$existing_file"
      # Clear trap and cleanup
      trap - INT TERM
      /usr/bin/ssh media "rm -rf $_q_tmpdir $_q_staging_dir 2>/dev/null || true"
      return 0
    else
      echo "" >&2
      echo "✅ New quality is better - proceeding with download" >&2
      echo "   Old file will be replaced" >&2
    fi
  else
    echo "✓ No existing download found" >&2
  fi
  echo "" >&2

  # Run yt-dlp remotely, then stage results to SSD NFS
  #
  # Remote stdout is reserved for video basenames (one per line).
  # All progress/info goes to stderr (yt-dlp >&2, echo >&2).
  local remote_script='
set -euo pipefail

tmpdir="$1"
cookie="$2"
staging_dir="$3"
url="$4"

mkdir -p "$staging_dir"

yt-dlp \
  --remote-components ejs:github \
  --cookies "$cookie" \
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
  -o "$tmpdir/%(uploader)s-%(title)s-[%(id)s].%(ext)s" \
  "$url" >&2 || true

shopt -s nullglob
video_files=("$tmpdir"/*.{mkv,mp4})
if (( ${#video_files[@]} == 0 )); then
  echo "⚠️  Subtitle error may have aborted download. Retrying without subtitles..." >&2
  yt-dlp \
    --remote-components ejs:github \
    --cookies "$cookie" \
    --embed-metadata \
    --embed-chapters \
    --embed-thumbnail \
    --convert-thumbnails jpg \
    -f bestvideo+bestaudio \
    --merge-output-format mkv \
    --restrict-filenames \
    -o "$tmpdir/%(uploader)s-%(title)s-[%(id)s].%(ext)s" \
    "$url" >&2
fi

# Drop sidecar images and subs: both are embedded in the mkv, and loose
# images confuse the Jellyfin poster scanner (folder-art bleed-through).
rm -f "$tmpdir"/*.{jpg,jpeg,png,webp,srt,vtt}

files=("$tmpdir"/*.{mkv,mp4,json,nfo} "$tmpdir"/*info.json)
video_files=("$tmpdir"/*.{mkv,mp4})
if (( ${#video_files[@]} == 0 )); then
  echo "❌ No video files found in $tmpdir" >&2
  ls -la "$tmpdir" >&2 || true
  exit 2
fi

echo "✅ Download complete. Staging to SSD..." >&2
rsync --info=progress2 --remove-source-files "${files[@]}" "$staging_dir/" >&2

# Output video basenames to stdout (Mac constructs final NFS-visible paths)
for f in "${files[@]}"; do
  case "$f" in
    *.mkv|*.mp4) echo "$(basename "$f")" ;;
  esac
done

# cleanup secrets + tmp
rm -f "$cookie" || true
rmdir "$tmpdir" 2>/dev/null || rm -rf "$tmpdir"

echo "✅ Staged to SSD." >&2
'

  # Stage 1: Download on media VM, rsync to SSD NFS
  local video_basenames
  if video_basenames="$(/usr/bin/ssh -o BatchMode=yes media "bash -s -- $(printf '%q' "$remote_tmpdir") $(printf '%q' "$remote_cookie") $(printf '%q' "$remote_staging_dir") $(printf '%q' "$url")" <<<"$remote_script")"; then
    # tmpdir cleaned by remote_script; staging dir still has files for stage 2
    echo "⏱️  [$(_yt_elapsed)] Download + SSD staging complete" >&2
  else
    local exit_code=$?
    echo "❌ Remote download failed (exit code: $exit_code)" >&2
    echo "" >&2
    echo "Troubleshooting steps:" >&2
    echo "  1. Update yt-dlp:     yt --update" >&2
    echo "  2. Refresh cookies:   re-export cookies to $LOCAL_YT_COOKIES" >&2
    echo "  3. Check URL:         open the URL in a browser to verify it's valid" >&2
    # Clear trap and cleanup both tmpdir and staging dir
    trap - INT TERM
    /usr/bin/ssh media "rm -rf $_q_tmpdir $_q_staging_dir 2>/dev/null || true"
    return 1
  fi

  # Stage 2: NAS-local copy from SSD (swift) to HDD (tank)
  local nas_staging_dir="${NAS_STAGING_BASE}/${staging_subdir}"
  local nas_final_dir="${NAS_FINAL_BASE}/${category}"

  echo "" >&2
  echo "📀 [$(_yt_elapsed)] Transferring to HDD on NAS..." >&2

  local nas_script="$_YT_NAS_SCRIPT"

  if /usr/bin/ssh -o BatchMode=yes "$NAS_SSH_HOST" "bash -s -- $(printf '%q' "$nas_staging_dir") $(printf '%q' "$nas_final_dir")" <<<"$nas_script"; then
    # Clear trap — staging dir cleaned by nas_script, tmpdir cleaned by remote_script
    trap - INT TERM
    echo "" >&2
    echo "✅ [$(_yt_elapsed)] Successfully downloaded to: $remote_final_dir" >&2
    # Output the final file paths to stdout for piping
    if [[ -n "$video_basenames" ]]; then
      local line
      for line in "${(@f)video_basenames}"; do
        echo "${remote_final_dir}/${line}"
      done
    fi
    return 0
  else
    local nas_exit=$?
    echo "❌ NAS transfer failed (exit code: $nas_exit)" >&2
    echo "" >&2
    echo "Files are safe on SSD staging. To manually complete the transfer:" >&2
    echo "  ssh $NAS_SSH_HOST 'rsync -rl --remove-source-files $(printf '%q' "$nas_staging_dir")/ $(printf '%q' "$nas_final_dir")/'" >&2
    echo "  ssh $NAS_SSH_HOST 'rmdir $(printf '%q' "$nas_staging_dir")'" >&2
    # Clear trap — don't delete staging dir since files are there for manual recovery
    trap - INT TERM
    return 1
  fi
}

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

rc=0
yt-dlp \
  --remote-components ejs:github \
  --cookies "$cookie" \
  --download-archive "$archive" \
  --playlist-items "$item" \
  --embed-metadata \
  --parse-metadata "%(playlist_index)03d - %(title)s:%(meta_title)s" \
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
  "$url" >&2 || rc=$?

shopt -s nullglob
video_files=("$tmpdir"/*.{mkv,mp4})
if (( ${#video_files[@]} == 0 )); then
  # Either already in the archive (skip) or a subtitle abort. Retry without
  # subs; a true skip still produces no file and is handled below.
  rc=0
  yt-dlp \
    --remote-components ejs:github \
    --cookies "$cookie" \
    --download-archive "$archive" \
    --playlist-items "$item" \
    --embed-metadata \
    --parse-metadata "%(playlist_index)03d - %(title)s:%(meta_title)s" \
    --embed-chapters \
    --embed-thumbnail \
    --convert-thumbnails jpg \
    -f bestvideo+bestaudio \
    --merge-output-format mkv \
    --restrict-filenames \
    -o "$tmpdir/%(playlist_index)03d-%(title)s-[%(id)s].%(ext)s" \
    "$url" >&2 || rc=$?
  video_files=("$tmpdir"/*.{mkv,mp4})
fi

# Drop sidecars (embedded in mkv; loose images confuse Jellyfin poster scan).
rm -f "$tmpdir"/*.{jpg,jpeg,png,webp,srt,vtt} 2>/dev/null || true

if (( ${#video_files[@]} == 0 )); then
  # Nothing downloaded. Discriminate: rc==0 means archived skip; rc!=0 is a
  # genuine download failure that must not be silently counted as skipped.
  rmdir "$tmpdir" 2>/dev/null || rm -rf "$tmpdir"
  if (( rc == 0 )); then
    exit 0   # archived skip — emit nothing
  else
    exit 3   # genuine download failure — emit nothing
  fi
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

  if ! $YT_SSH -o BatchMode=yes media 'command -v yt-dlp >/dev/null 2>&1' < /dev/null; then
    echo "❌ yt-dlp not found on media VM" >&2
    return 1
  fi

  # Upload cookie once into a dedicated remote tmp dir.
  local remote_cookie_dir
  remote_cookie_dir="$($YT_SSH -o BatchMode=yes media 'mktemp -d /tmp/yt.pl.XXXXXX' < /dev/null)" || {
    echo "❌ Failed to create remote temp dir" >&2
    return 1
  }
  local _q_cookie_dir=$(printf '%q' "$remote_cookie_dir")
  trap "$YT_SSH -o BatchMode=yes media \"rm -rf $_q_cookie_dir 2>/dev/null || true\" 2>/dev/null; trap - INT TERM; return 130" INT TERM

  local remote_cookie="$remote_cookie_dir/cookies.txt"
  echo "🍪 [$(_yt_elapsed)] Copying cookies to media VM..." >&2
  $YT_SSH -o BatchMode=yes media "umask 077 && cat > $(printf '%q' "$remote_cookie")" < "$LOCAL_YT_COOKIES" || {
    echo "❌ Failed to copy cookies to media VM" >&2
    $YT_SSH -o BatchMode=yes media "rm -rf $_q_cookie_dir 2>/dev/null || true"
    trap - INT TERM
    return 1
  }

  # Resolve the playlist title -> slug, confirm/override.
  echo "🔍 [$(_yt_elapsed)] Fetching playlist title..." >&2
  local playlist_title
  playlist_title="$($YT_SSH -o BatchMode=yes media "yt-dlp --remote-components ejs:github --flat-playlist --playlist-items 1 --print '%(playlist_title)s' --cookies $(printf '%q' "$remote_cookie") $(printf '%q' "$url") 2>/dev/null" < /dev/null || echo "")"

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
      $YT_SSH -o BatchMode=yes media "rm -rf $_q_cookie_dir 2>/dev/null || true"
      trap - INT TERM
      return 1
      ;;
    *)
      slug="$(_yt_slugify "$answer")"
      if [[ -z "$slug" ]]; then
        echo "❌ '$answer' slugifies to an empty name" >&2
        $YT_SSH -o BatchMode=yes media "rm -rf $_q_cookie_dir 2>/dev/null || true"
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
    $YT_SSH -o BatchMode=yes media "rm -rf $_q_cookie_dir 2>/dev/null || true"
    trap - INT TERM
    return 1
  }

  # Count playlist items.
  local count
  count="$($YT_SSH -o BatchMode=yes media "yt-dlp --remote-components ejs:github --flat-playlist --print '%(playlist_index)s' --cookies $(printf '%q' "$remote_cookie") $(printf '%q' "$url") 2>/dev/null | wc -l" | tr -d '[:space:]')"
  if [[ -z "$count" || "$count" == "0" ]]; then
    echo "❌ Playlist is empty or could not be read" >&2
    $YT_SSH -o BatchMode=yes media "rm -rf $_q_cookie_dir 2>/dev/null || true"
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

    # Re-arm trap to also clean up this item's tmp and staging dirs on INT/TERM.
    local _q_item_tmpdir=$(printf '%q' "$item_tmpdir")
    local _q_item_staging=$(printf '%q' "$item_staging")
    trap "$YT_SSH -o BatchMode=yes media \"rm -rf $_q_cookie_dir $_q_item_tmpdir $_q_item_staging 2>/dev/null || true\" 2>/dev/null; trap - INT TERM; return 130" INT TERM

    # Stage 1: download item + rsync to SSD staging.
    local basenames
    if ! basenames="$($YT_SSH -o BatchMode=yes media "bash -s -- $(printf '%q' "$item_tmpdir") $(printf '%q' "$remote_cookie") $(printf '%q' "$item_staging") $(printf '%q' "$url") $(printf '%q' "$n") $(printf '%q' "$archive_remote")" <<<"$_YT_PLAYLIST_ITEM_SCRIPT")"; then
      echo "❌ [$n/$count] download/staging failed" >&2
      $YT_SSH -o BatchMode=yes media "rm -rf $(printf '%q' "$item_tmpdir") $(printf '%q' "$item_staging") 2>/dev/null || true"
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
  $YT_SSH -o BatchMode=yes media "rm -rf $_q_cookie_dir 2>/dev/null || true"
  trap - INT TERM

  echo "" >&2
  echo "✅ [$(_yt_elapsed)] Playlist '$slug': downloaded $downloaded, skipped $skipped, failed $failed" >&2
  (( failed == 0 ))
}

# Slugify a string for use as a directory name (lowercase ASCII, dashes).
_yt_slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

# Help text function
_yt_show_help() {
  cat >&2 <<'EOF'
yt - Download videos to media VM with categorization

USAGE:
  yt -SHORTCUT URL
  yt --category CATEGORY URL
  yt --update
  yt --help

DESCRIPTION:
  Downloads YouTube (and other) videos directly on the media VM and saves them to the correct subdirectory in the movies dataset.

  The script copies a youtube cookie from ~/.config/yt-dlp/cookies/cookies.txt onto the media VM.
  Use a browser plugin to copy the cookie from a browser to the local config directory.

  The script handles:
    - quality selection
    - duplicate detection
    - metadata embedding
    - destination directory according to category

CATEGORIES:
  -g  training          Training and gym/workout videos
  -y  youtube           General YouTube content
  -c  create            Creative/maker content
  -m  music             Music videos and performances
  -h  humanity          Humanities and cultural content
  -t  travel            Travel videos and vlogs
  -e  math+engineering  Math and engineering content

OPTIONS:
  --category CATEGORY    Specify category by name (alternative to shortcuts)
  -p, --playlist URL     Download an entire playlist into its own library dir
  --update               Update yt-dlp on the media VM
  --help                 Show this help message

EXAMPLES:
  yt -g "https://youtu.be/C4TVr2NtEg8"
  yt -m "https://youtube.com/watch?v=dQw4w9WgXcQ"
  yt --category training "https://youtu.be/C4TVr2NtEg8"

  Download a playlist as its own Jellyfin library:
    yt -p "https://www.youtube.com/playlist?list=PLxxxxxxxx"

  Update yt-dlp on the media VM:
    yt --update

  Pipe to epm for photo extraction:
    yt -g "https://youtu.be/C4TVr2NtEg8" | epm

REQUIREMENTS:
  - YouTube cookies must be exported to: ~/.config/yt-dlp/cookies/cookies.txt
  - SSH access to 'media' host must be configured
  - yt-dlp must be installed on the media VM

FILES:
  Final videos are saved to: /mnt/nfs/movies/youtube/{CATEGORY}/
  Playlists are saved to:    /mnt/nfs/movies/youtube/{PLAYLIST-SLUG}/

EOF
}

# Main yt command with flag parsing
yt() {
  setopt local_options pipefail

  # Valid categories
  local -a valid_categories=(training youtube create music humanity travel math+engineering)

  # Show help if no arguments or help requested
  if [[ $# -eq 0 ]] || [[ "$1" == "--help" ]]; then
    _yt_show_help
    return 0
  fi

  # Parse flags using zparseopts
  local -A opts
  zparseopts -D -E -A opts -- g y c m h t e p -category: -help -update -playlist

  # Handle --update before anything else
  if (( ${+opts[--update]} )); then
    echo "🔄 Updating yt-dlp on media VM..." >&2
    /usr/bin/ssh -o BatchMode=yes -t media 'sudo apt update && sudo apt install --only-upgrade yt-dlp' >&2
    return $?
  fi

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

  # Map shortcut flags to categories
  local category
  if (( ${+opts[-g]} )); then
    category="training"
  elif (( ${+opts[-y]} )); then
    category="youtube"
  elif (( ${+opts[-c]} )); then
    category="create"
  elif (( ${+opts[-m]} )); then
    category="music"
  elif (( ${+opts[-h]} )); then
    category="humanity"
  elif (( ${+opts[-t]} )); then
    category="travel"
  elif (( ${+opts[-e]} )); then
    category="math+engineering"
  elif [[ -n "${opts[--category]}" ]]; then
    category="${opts[--category]}"
  fi

  if [[ -z "$category" ]]; then
    echo "❌ Error: Category shortcut is required" >&2
    echo "" >&2
    echo "Usage: yt -g|-y|-c|-m|-h|-t|-e URL" >&2
    echo "   or: yt --category CATEGORY URL" >&2
    echo "" >&2
    echo "Run 'yt --help' for more information" >&2
    return 1
  fi

  # Validate category
  if [[ ! ${valid_categories[(ie)$category]} -le ${#valid_categories} ]]; then
    echo "❌ Error: Invalid category '$category'" >&2
    echo "" >&2
    echo "Valid categories: ${(j:, :)valid_categories}" >&2
    echo "" >&2
    echo "Run 'yt --help' for more information" >&2
    return 1
  fi

  # Extract URL (first remaining positional argument)
  local url="$1"

  if [[ -z "$url" ]]; then
    echo "❌ Error: URL is required" >&2
    echo "" >&2
    echo "Usage: yt -g|-y|-c|-m|-h|-t|-e URL" >&2
    echo "" >&2
    echo "Run 'yt --help' for more information" >&2
    return 1
  fi

  # Call the main download function with noglob handling
  noglob _ytdl_on_media_vm "$category" "$url"
}
