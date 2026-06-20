#!/usr/bin/env bats

# ---------------------------------------------------------------------------
# Stub modes (set via STUB_MODE env var in each test):
#   normal  – media bash -s emits a basename; nas succeeds  (default)
#   skip    – media bash -s emits nothing (item already archived); nas succeeds
#   nasfail – media bash -s emits a basename; nas arm exits 1
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
