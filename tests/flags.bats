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
