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
