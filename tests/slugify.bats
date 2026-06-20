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
