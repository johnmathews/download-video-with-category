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
