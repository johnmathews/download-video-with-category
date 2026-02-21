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

_ytdl_on_media_vm() {
  setopt local_options pipefail

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
  echo "🍪 Copying cookies to media VM..." >&2
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
  echo "🔍 Fetching video info..." >&2
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
  echo "🔎 Checking for existing downloads..." >&2
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
  --sub-langs "en.*,nl,de,es" \
  --write-auto-subs \
  --embed-subs \
  -f bestvideo+bestaudio \
  --merge-output-format mkv \
  --restrict-filenames \
  -o "$tmpdir/%(uploader)s-%(title)s-[%(id)s].%(ext)s" \
  "$url" >&2

shopt -s nullglob
files=("$tmpdir"/*.{mkv,mp4,jpg,webp,srt,vtt,json,nfo} "$tmpdir"/*info.json)
if (( ${#files[@]} == 0 )); then
  echo "❌ No output files found in $tmpdir" >&2
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
    :
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
  echo "📀 Transferring to HDD on NAS..." >&2

  local nas_script='
set -euo pipefail

staging_dir="$1"
final_dir="$2"

if [ ! -d "$staging_dir" ]; then
  echo "❌ Staging dir not found: $staging_dir" >&2
  exit 1
fi

mkdir -p "$final_dir"
rsync --info=progress2 --remove-source-files "$staging_dir/" "$final_dir/" >&2
rmdir "$staging_dir" 2>/dev/null || true

echo "✅ Done." >&2
'

  if /usr/bin/ssh -o BatchMode=yes "$NAS_SSH_HOST" "bash -s -- $(printf '%q' "$nas_staging_dir") $(printf '%q' "$nas_final_dir")" <<<"$nas_script"; then
    # Clear trap — staging dir cleaned by nas_script, tmpdir cleaned by remote_script
    trap - INT TERM
    echo "" >&2
    echo "✅ Successfully downloaded to: $remote_final_dir" >&2
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
    echo "  ssh $NAS_SSH_HOST 'rsync -a --remove-source-files $(printf '%q' "$nas_staging_dir")/ $(printf '%q' "$nas_final_dir")/'" >&2
    echo "  ssh $NAS_SSH_HOST 'rmdir $(printf '%q' "$nas_staging_dir")'" >&2
    # Clear trap — don't delete staging dir since files are there for manual recovery
    trap - INT TERM
    return 1
  fi
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
  --update               Update yt-dlp on the media VM
  --help                 Show this help message

EXAMPLES:
  yt -g "https://youtu.be/C4TVr2NtEg8"
  yt -m "https://youtube.com/watch?v=dQw4w9WgXcQ"
  yt --category training "https://youtu.be/C4TVr2NtEg8"

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
  zparseopts -D -E -A opts -- g y c m h t e -category: -help -update

  # Handle --update before anything else
  if (( ${+opts[--update]} )); then
    echo "🔄 Updating yt-dlp on media VM..." >&2
    /usr/bin/ssh -o BatchMode=yes -t media 'sudo apt update && sudo apt install --only-upgrade yt-dlp' >&2
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
