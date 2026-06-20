#!/usr/bin/env bats

# ---------------------------------------------------------------------------
# Stub modes (set via STUB_MODE env var in each test):
#   normal  – media bash -s emits a basename; nas succeeds  (default)
#   skip    – media bash -s emits nothing (item already archived); nas succeeds
#   nasfail – media bash -s emits a basename; nas arm exits 1
#   dlfail  – media bash -s exits 3 (genuine yt-dlp error), emits nothing
# ---------------------------------------------------------------------------

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
STUB_MODE="\${STUB_MODE:-normal}"
case "\$cmd" in
  *"command -v yt-dlp"*) exit 0 ;;
  *"playlist_title"*)    echo "Test Playlist"; exit 0 ;;
  *"playlist_index"*)    echo "3"; exit 0 ;;
  *"mktemp -d"*)         echo "/tmp/yt.stub.\$RANDOM"; exit 0 ;;
  *"umask 077"*)         exit 0 ;;
  *"mkdir -p"*)          exit 0 ;;
  *"rm -rf"*)            exit 0 ;;
  # NAS stage-2 arm — matched BEFORE the generic bash -s arm so the two
  # branches are unambiguously distinguished.
  *" nas "*"bash -s"*)
    case "\$STUB_MODE" in
      nasfail) exit 1 ;;
      *)       exit 0 ;;
    esac
    ;;
  # Media stage-1 arm (download + SSD staging).
  *"bash -s"*)
    case "\$STUB_MODE" in
      skip)    exit 0 ;;   # emit nothing -> item already archived
      dlfail)  exit 3 ;;   # genuine yt-dlp error -> emit nothing, non-zero
      *)       echo "001-fake-\$RANDOM-[id].mkv"; exit 0 ;;
    esac
    ;;
  *) exit 0 ;;
esac
STUBEOF
  chmod +x "$STUB"
}

run_pl() {
  # $1 = confirm input ; $2 = playlist url ; $3 = optional STUB_MODE
  local mode="${3:-normal}"
  run env STUB_MODE="$mode" zsh -c "source ./yt.sh; YT_SSH='$STUB'; LOCAL_YT_COOKIES='$CK'; _yt_playlist_on_media_vm '$2' <<< '$1'"
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
  [[ "$output" == *"/mnt/nfs/movies/youtube/test-playlist/"* ]]
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

@test "all items skipped: reports downloaded 0 skipped 3 failed 0 and returns 0" {
  run_pl "y" "https://www.youtube.com/playlist?list=PLtest" "skip"
  [ "$status" -eq 0 ]
  [[ "$output" == *"downloaded 0, skipped 3, failed 0"* ]]
}

@test "NAS failure: returns non-zero, reports failed > 0, and processes all items" {
  run_pl "y" "https://www.youtube.com/playlist?list=PLtest" "nasfail"
  [ "$status" -ne 0 ]
  [[ "$output" == *"failed 3"* ]]
  # All 3 items were attempted (3 media stage-1 bash -s calls)
  media_dl=$(grep "bash -s" "$LOG" | grep -vc " nas ")
  [ "$media_dl" -eq 3 ]
}

# ---------------------------------------------------------------------------
# Loop-level failure test: dlfail stub mode
# ---------------------------------------------------------------------------

@test "stage-1 yt-dlp failure: counted as failed (not skipped), returns non-zero" {
  run_pl "y" "https://www.youtube.com/playlist?list=PLtest" "dlfail"
  [ "$status" -ne 0 ]
  [[ "$output" == *"failed 3"* ]]
  [[ "$output" != *"skipped 3"* ]]
  [[ "$output" == *"skipped 0"* ]]
}

# ---------------------------------------------------------------------------
# Direct item-script tests: run _YT_PLAYLIST_ITEM_SCRIPT locally via bash
# with a fake yt-dlp on PATH and real temp dirs.
# ---------------------------------------------------------------------------

# Helper: extract the item script from yt.sh and return it in ITEM_SCRIPT
_load_item_script() {
  ITEM_SCRIPT="$(zsh -c 'source ./yt.sh; printf "%s" "$_YT_PLAYLIST_ITEM_SCRIPT"')"
}

# Helper: build fake yt-dlp and rsync wrappers in BATS_TEST_TMPDIR/bin/.
# FAKE_YTDLP_MODE controls yt-dlp behaviour:
#   success  – creates a .mkv in FAKE_TMPDIR and exits 0
#   skip     – exits 0, creates no file
#   fail     – exits 1, creates no file
# The fake rsync moves files from src dir to dest dir (emulates
# --remove-source-files) so the success path of the script completes cleanly
# on macOS where the system rsync lacks --info=progress2.
_make_fake_ytdlp() {
  local bindir="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$bindir"
  cat > "$bindir/yt-dlp" <<'FAKEEOF'
#!/usr/bin/env bash
mode="${FAKE_YTDLP_MODE:-skip}"
case "$mode" in
  success)
    tmpd="${FAKE_TMPDIR:?FAKE_TMPDIR not set}"
    touch "$tmpd/001-fake-video-[abcd1234].mkv"
    exit 0
    ;;
  skip)
    exit 0
    ;;
  fail)
    exit 1
    ;;
esac
FAKEEOF
  chmod +x "$bindir/yt-dlp"

  # Fake rsync: move source files to the destination directory so that the
  # item script's post-rsync echo loop finds basenames in staging_dir.
  cat > "$bindir/rsync" <<'RSYNCEOF'
#!/usr/bin/env bash
# Minimal stub: move all source files into the last argument (dest dir).
# Ignore flags; find the last arg as dest and the second-to-last as src glob.
args=("$@")
dest="${args[-1]}"
mkdir -p "$dest"
# Collect file args (non-flag, non-dest, non-dir arguments).
for arg in "${args[@]}"; do
  case "$arg" in
    -*) ;;  # skip flags
    */\*) ;;  # skip glob patterns if any
    *)
      if [ -f "$arg" ]; then
        mv "$arg" "$dest/"
      fi
      ;;
  esac
done
exit 0
RSYNCEOF
  chmod +x "$bindir/rsync"

  FAKE_BIN="$bindir"
}

@test "item-script success: exits 0 and emits the video basename" {
  _load_item_script
  _make_fake_ytdlp

  local idir staging archive cookie
  idir="$(mktemp -d)"
  staging="$(mktemp -d)"
  archive="$BATS_TEST_TMPDIR/archive.txt"
  cookie="$BATS_TEST_TMPDIR/cookies.txt"
  printf 'fake-cookie\n' > "$cookie"

  run env PATH="$FAKE_BIN:$PATH" FAKE_YTDLP_MODE=success FAKE_TMPDIR="$idir" \
    bash -c "$ITEM_SCRIPT" _ "$idir" "$cookie" "$staging" "https://fake/url" "1" "$archive"

  [ "$status" -eq 0 ]
  [[ "$output" == *".mkv"* ]]

  rm -rf "$idir" "$staging"
}

@test "item-script archived-skip: exits 0 and emits nothing" {
  _load_item_script
  _make_fake_ytdlp

  local idir staging archive cookie
  idir="$(mktemp -d)"
  staging="$(mktemp -d)"
  archive="$BATS_TEST_TMPDIR/archive2.txt"
  cookie="$BATS_TEST_TMPDIR/cookies.txt"
  printf 'fake-cookie\n' > "$cookie"

  run env PATH="$FAKE_BIN:$PATH" FAKE_YTDLP_MODE=skip \
    bash -c "$ITEM_SCRIPT" _ "$idir" "$cookie" "$staging" "https://fake/url" "1" "$archive"

  [ "$status" -eq 0 ]
  [ -z "$output" ]

  rm -rf "$idir" "$staging"
}

@test "item-script real-failure: exits 3 and emits nothing" {
  _load_item_script
  _make_fake_ytdlp

  local idir staging archive cookie
  idir="$(mktemp -d)"
  staging="$(mktemp -d)"
  archive="$BATS_TEST_TMPDIR/archive3.txt"
  cookie="$BATS_TEST_TMPDIR/cookies.txt"
  printf 'fake-cookie\n' > "$cookie"

  run env PATH="$FAKE_BIN:$PATH" FAKE_YTDLP_MODE=fail \
    bash -c "$ITEM_SCRIPT" _ "$idir" "$cookie" "$staging" "https://fake/url" "1" "$archive"

  [ "$status" -eq 3 ]
  [ -z "$output" ]

  rm -rf "$idir" "$staging"
}
