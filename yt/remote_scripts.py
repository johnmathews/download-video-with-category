"""Bash that runs ON the media VM or the NAS, piped to `bash -s -- args...` over ssh.

These are deliberately kept as shell: they run where yt-dlp, rsync and the NFS mounts are,
and they take their inputs as positional arguments (never interpolated), so the Python side
only ever quotes. Remote stdout is reserved for video basenames / structured results; all
progress goes to stderr.

Subtitle flags (all three download scripts, keep them in step):
  --sub-format "srt/ttml/vtt/best"  NOT srv3. `--sub-format` is a preference list, and
      YouTube offers srv3 for every auto-translated track, so srv3 used to win — then
      `--convert-subs srt` handed it to ffmpeg, which has no srv3 demuxer, and yt-dlp
      exited 1. srt makes the conversion a no-op; ttml takes yt-dlp's own dfxp2srt path.
  --sub-langs "en,en-orig,en-US,en-GB"  NOT "en.*". yt-dlp names auto-translations
      "<target>-<source>", so the glob also matched en-en and en-de — extra tracks, each
      costing a --sleep-subtitles pause, which is what produced HTTP 429.
"""

# Stage-2 transfer script (NAS-local SSD swift -> HDD tank), shared by every mode.
NAS_SCRIPT = r"""
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
"""

# Single-video stage 1: yt-dlp into $tmpdir, then rsync to SSD staging.
#   $1 tmpdir  $2 cookie  $3 staging_dir  $4 url
# stdout = video basenames (one per line).
SINGLE_ITEM_SCRIPT = r"""
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
  --sub-langs "en,en-orig,en-US,en-GB" \
  --write-subs \
  --write-auto-subs \
  --embed-subs \
  --convert-subs srt \
  --sub-format "srt/ttml/vtt/best" \
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
"""

# Per-item playlist download script (stage 1): yt-dlp one playlist item to
# $tmpdir, then rsync to SSD staging. stdout = video basenames (skip => empty).
#   $1 tmpdir  $2 cookie  $3 staging_dir  $4 url  $5 item  $6 archive
# exit 0 with no output = archived skip; exit 3 = genuine download failure.
PLAYLIST_ITEM_SCRIPT = r"""
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
  --sub-langs "en,en-orig,en-US,en-GB" \
  --write-subs \
  --write-auto-subs \
  --embed-subs \
  --convert-subs srt \
  --sub-format "srt/ttml/vtt/best" \
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
    # Archived skip: nothing was staged, so drop the staging dir this script created.
    # Doing it here rather than from Python saves an ssh round trip per skipped item —
    # a re-run of a fully archived playlist is otherwise one connection per item.
    rmdir "$staging_dir" 2>/dev/null || true
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
"""

# Fitness mode, discovery (media VM): list shows and seasons in the fitness tree.
# stdout: one line per season "<show>\t<season number>\t<season title>\t<episode count>\t<order>",
# order = feed (newest first, numbered down from 999) | course (oldest first, 1..N; the default),
# read from the .order marker file in the season dir. "<show>\t\t\t0\t" for a show with no seasons.
FITNESS_LIST_SCRIPT = r"""
set -uo pipefail
base="$1"
shopt -s nullglob
for sd in "$base"/*/; do
  sd="${sd%/}"; show="${sd##*/}"
  [ -d "$sd" ] || continue
  any=0
  for d in "$sd"/Season\ */; do
    d="${d%/}"; any=1
    n="${d##*/Season }"; n=$((10#$n))
    t=""; [ -f "$d/season.nfo" ] && t=$(sed -n "s:.*<title>\(.*\)</title>.*:\1:p" "$d/season.nfo" | head -1 | sed "s/&amp;/\&/g; s/&lt;/</g; s/&gt;/>/g; s/&quot;/\"/g")
    c=0; for f in "$d"/*.mkv "$d"/*.mp4 "$d"/*.webm; do c=$((c+1)); done
    o="course"; [ -f "$d/.order" ] && o=$(tr -d "[:space:]" < "$d/.order")
    printf "%s\t%d\t%s\t%d\t%s\n" "$show" "$n" "$t" "$c" "$o"
  done
  if [ $any = 0 ]; then printf "%s\t\t\t0\t\n" "$show"; fi
done
exit 0
"""

# Fitness mode, stage 0 (media VM): resolve "<Show>/<Season>" to a season dir
# under the fitness tree and compute the next episode number.
#   $1 fitness base dir (NFS view)   $2 show   $3 season spec   $4 order to set ("" = leave as is)
# season spec: "3" | "Tutorials" (existing season by number or nfo title) |
#              "4:Mobility" (create Season 04 titled Mobility; creates the show too)
# order: feed = newest first, episodes numbered DOWN from 999; course = oldest first, 1..N.
# stdout (6 lines): <show dir> <season dir> <next episode number> <episode digits> <order> <order-was-missing 0|1>
# exit 4 = unsafe show name, or season/show not found and no ":Name" given to create it.
FITNESS_RESOLVE_SCRIPT = r"""
set -euo pipefail
base="$1"; show="$2"; spec="$3"; set_order="${4:-}"
# The show is the only user-supplied path component; season dirs are always
# "Season NN". Reject anything that would escape $base or create a hidden dir.
# The Python side validates too — this is defence in depth for any other caller.
case "$show" in
  ""|.*|*/*) echo "❌ unsafe show name: $show" >&2; exit 4 ;;
esac
show_dir="$base/$show"
create_name=""
case "$spec" in *:*) create_name="${spec#*:}"; spec="${spec%%:*}" ;; esac

season_dir=""
if [[ "$spec" =~ ^[0-9]+$ ]]; then
  num=$((10#$spec))
  cand=$(printf "%s/Season %02d" "$show_dir" "$num")
  [ -d "$cand" ] && season_dir="$cand"
else
  # match a season.nfo <title> (case-insensitive) or the folder name
  shopt -s nullglob
  for d in "$show_dir"/Season\ */; do
    d="${d%/}"
    t=""
    [ -f "$d/season.nfo" ] && t=$(sed -n "s:.*<title>\(.*\)</title>.*:\1:p" "$d/season.nfo" | head -1 | sed "s/&amp;/\&/g; s/&lt;/</g; s/&gt;/>/g; s/&quot;/\"/g")
    if [ "${t,,}" = "${spec,,}" ] || [ "${d##*/}" = "$spec" ]; then season_dir="$d"; break; fi
  done
  num=""
fi

if [ -z "$season_dir" ]; then
  if [ -z "$create_name" ] || [ -z "${num:-}" ]; then
    echo "❌ No season \"$spec\" under $show_dir. To create one: <Show>/<N>:<Name>" >&2
    ls -1d "$show_dir"/Season\ */ 2>/dev/null | sed "s|.*/||" >&2 || true
    exit 4
  fi
  season_dir=$(printf "%s/Season %02d" "$show_dir" "$num")
  if [ ! -d "$show_dir" ]; then
    mkdir -p "$show_dir"
    printf "<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\"?>\n<tvshow>\n  <title>%s</title>\n  <lockdata>false</lockdata>\n</tvshow>\n" "$(printf "%s" "$show" | sed "s/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g")" > "$show_dir/tvshow.nfo"
    echo "🆕 Created show $show_dir" >&2
  fi
  mkdir -p "$season_dir"
  printf "<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\"?>\n<season>\n  <title>%s</title>\n  <seasonnumber>%d</seasonnumber>\n  <lockdata>false</lockdata>\n</season>\n" "$(printf "%s" "$create_name" | sed "s/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g")" "$num" > "$season_dir/season.nfo"
  echo "🆕 Created $season_dir (\"$create_name\")" >&2
fi

snum="${season_dir##*/Season }"; snum=$((10#$snum))

# order marker: set if asked, else read; missing => course (reported so the caller can ask)
order_missing=0
if [ -n "$set_order" ]; then
  case "$set_order" in feed|course) printf "%s\n" "$set_order" > "$season_dir/.order" ;; *) echo "❌ order must be feed or course, got: $set_order" >&2; exit 5 ;; esac
fi
if [ -f "$season_dir/.order" ]; then order=$(tr -d "[:space:]" < "$season_dir/.order"); else order="course"; order_missing=1; fi
[ "$order" = feed ] || order="course"

# next episode number and digit width from what is already there
max=0; min=1000; width=2; count=0
shopt -s nullglob
for f in "$season_dir"/*.mkv "$season_dir"/*.mp4 "$season_dir"/*.webm; do
  b="${f##*/}"
  if [[ "$b" =~ S[0-9]{2}E([0-9]{2,3}) ]]; then
    e=${BASH_REMATCH[1]}; [ ${#e} -ge 3 ] && width=3
    n=$((10#$e)); [ $n -gt $max ] && max=$n; [ $n -lt $min ] && min=$n; count=$((count+1))
  fi
done
if [ "$order" = feed ]; then
  # newest first: count down from 999
  width=3
  if [ $count -eq 0 ]; then next=999; else next=$((min - 1)); fi
  if [ $next -lt 1 ]; then echo "❌ season is full (episode numbers exhausted)" >&2; exit 6; fi
else
  next=$((max + 1)); [ $next -ge 100 ] && width=3
fi
printf "%s\n%s\n%d\n%d\n%s\n%d\n" "$show_dir" "$season_dir" "$next" "$width" "$order" "$order_missing"
"""

# Fitness mode, stage 1 (media VM): download one video into $tmpdir with sidecars,
# rename to "<Show> SnnEnn - <yt-dlp name>-[id].ext", stage to SSD.
#   $1 tmpdir $2 cookie $3 staging_dir $4 url $5 show $6 season-number $7 episode $8 digits
# stdout = staged video basenames.
FITNESS_ITEM_SCRIPT = r"""
set -euo pipefail
tmpdir="$1"; cookie="$2"; staging_dir="$3"; url="$4"
show="$5"; season="$6"; episode="$7"; width="$8"
mkdir -p "$staging_dir"

dl() {
  yt-dlp \
    --remote-components ejs:github \
    --cookies "$cookie" \
    --embed-metadata \
    --embed-chapters \
    --embed-thumbnail \
    --write-thumbnail \
    --convert-thumbnails jpg \
    --write-info-json \
    "$@" \
    -f bestvideo+bestaudio \
    --merge-output-format mkv \
    --restrict-filenames \
    -o "$tmpdir/%(uploader)s-%(title)s-[%(id)s].%(ext)s" \
    "$url" >&2
}
dl --sub-langs "en,en-orig,en-US,en-GB" --write-subs --write-auto-subs --embed-subs --convert-subs srt --sub-format "srt/ttml/vtt/best" --sleep-subtitles 1 || true
shopt -s nullglob
video_files=("$tmpdir"/*.{mkv,mp4})
if (( ${#video_files[@]} == 0 )); then
  echo "⚠️  Subtitle error may have aborted download. Retrying without subtitles..." >&2
  dl
  video_files=("$tmpdir"/*.{mkv,mp4})
fi
# Subtitles are embedded in the mkv; drop every loose subtitle sidecar (srt/vtt/srv3/ttml/...).
rm -f "$tmpdir"/*.{srt,vtt,srv3,ttml,ass,json3} 2>/dev/null || true
if (( ${#video_files[@]} == 0 )); then
  echo "❌ No video files found in $tmpdir" >&2; ls -la "$tmpdir" >&2 || true; exit 2
fi

# Rename every sidecar sharing the video stem: "<Show> SnnEnn - <stem>.<ext>"
prefix=$(printf "%s S%02dE%0*d - " "$show" "$season" "$width" "$episode")
for v in "${video_files[@]}"; do
  stem="${v%.*}"; base="${stem##*/}"
  for f in "$tmpdir/$base".* "$tmpdir/$base"-*; do
    [ -e "$f" ] || continue
    mv -n "$f" "$tmpdir/$prefix${f##*/}"
  done
done

files=("$tmpdir"/*)
rsync --info=progress2 --remove-source-files "${files[@]}" "$staging_dir/" >&2
for f in "${files[@]}"; do
  case "$f" in *.mkv|*.mp4) echo "$(basename "$f")" ;; esac
done
rm -f "$cookie" || true
rmdir "$tmpdir" 2>/dev/null || rm -rf "$tmpdir"
"""

# `yt --update`: refresh the official standalone yt-dlp binary in /usr/local/bin (the apt/PPA
# package lags for months and then YouTube answers 403 mid-download). Needs a tty for sudo.
UPDATE_COMMAND = (
    "set -e; tmp=$(mktemp); "
    'curl -fsSL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux -o "$tmp" '
    '&& sudo install -m 0755 -o root -g root "$tmp" /usr/local/bin/yt-dlp && rm -f "$tmp" '
    '&& echo "yt-dlp now $(yt-dlp --version)"'
)
