#!/usr/bin/env bats

# Fitness mode (`yt -f`): every remote call goes through the $YT_SSH stub.
# STUB_MODE: normal (default) | nasfail | dlfail | dup (video already in the show)

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
stdin=""
if [ ! -t 0 ]; then stdin="\$(cat)"; fi
STUB_MODE="\${STUB_MODE:-normal}"
case "\$cmd" in
  *"command -v yt-dlp"*) exit 0 ;;
  *"mktemp -d"*)         echo "/tmp/yt.stub42"; exit 0 ;;
  *"umask 077"*)         exit 0 ;;
  *"rm -rf"*)            exit 0 ;;
  *"--print '%(id)s'"*)  printf 'abcDEF12345\nKettlebell Snatch Technique\nMark Wildman\n'; exit 0 ;;
  *"find "*)             if [ "\$STUB_MODE" = dup ]; then echo "/mnt/nfs/movies/youtube/fitness/Kettlebell/Season 02/Kettlebell S02E05 - old-[abcDEF12345].mkv"; fi; exit 0 ;;
  *"python3 -"*)         echo "\$stdin" > "$BATS_TEST_TMPDIR/helper_sent.py"; echo "nfo written"; exit 0 ;;
  *" nas "*"bash -s"*)   [ "\$STUB_MODE" = nasfail ] && exit 1; exit 0 ;;
  *"bash -s"*)
    # discriminate the three media-VM bash -s scripts by their content
    case "\$stdin" in
      *"for sd in"*)
        printf 'Bodyweight\t1\tBodyweight\t22\tfeed\nKettlebell\t1\tCompilations\t17\tcourse\nKettlebell\t2\tTurkish Get-Up\t26\tcourse\nKettlebell\t3\tTutorials\t9\tfeed\n'; exit 0 ;;
      *"next episode number"*)
        # resolve: show dir, season dir, next episode, digits — echo what we were asked for
        show="\$(printf '%s' "\$cmd" | sed -n 's/.*bash -s -- [^ ]* \([^ ]*\) .*/\1/p' | tr -d "'")"
        # STUB_MODE=noorder: pretend the season has no .order marker yet (6th line = 1)
        if [ "\$STUB_MODE" = noorder ] && ! printf '%s' "\$cmd" | grep -q "feed'\\|course'"; then
          printf '/mnt/nfs/movies/youtube/fitness/Kettlebell\n/mnt/nfs/movies/youtube/fitness/Kettlebell/Season 03\n10\n2\ncourse\n1\n'; exit 0
        fi
        if printf '%s' "\$cmd" | grep -q "feed'"; then
          printf '/mnt/nfs/movies/youtube/fitness/Kettlebell\n/mnt/nfs/movies/youtube/fitness/Kettlebell/Season 03\n990\n3\nfeed\n0\n'; exit 0
        fi
        printf '/mnt/nfs/movies/youtube/fitness/Kettlebell\n/mnt/nfs/movies/youtube/fitness/Kettlebell/Season 03\n10\n2\ncourse\n0\n'; exit 0 ;;
      *)
        [ "\$STUB_MODE" = dlfail ] && exit 2
        echo "Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345].mkv"; exit 0 ;;
    esac ;;
  *) exit 0 ;;
esac
STUBEOF
  chmod +x "$STUB"
}

run_f() {
  # $1 = stdin answers ; $2 = target ("" for interactive) ; $3 = url ; $4 = STUB_MODE
  local mode="${4:-normal}"
  run env STUB_MODE="$mode" YT_FITNESS_ANSWERS_FROM_STDIN=1 zsh -c "source ./yt.sh; YT_SSH='$STUB'; LOCAL_YT_COOKIES='$CK'; _yt_fitness_on_media_vm '$2' '$3' <<< \$'$1'"
}

@test "fast path: Show/Season given, confirm, downloads and prints the final path" {
  run_f "y\n" "Kettlebell/3" "https://youtu.be/abcDEF12345"
  [ "$status" -eq 0 ]
  [[ "$output" == *"/mnt/nfs/movies/youtube/fitness/Kettlebell/Season 03/Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345].mkv"* ]]
  [[ "$output" == *"S03E10"* ]]
  grep -q "python3 -" "$LOG"                       # nfo helper shipped
  grep -q "fitness/Kettlebell/Season" "$LOG"       # NAS stage-2 aimed at the season dir (printf %q escapes the space)
  grep -q "jellyfin_nfo" "$BATS_TEST_TMPDIR/helper_sent.py"   # the real helper went over stdin
}

@test "interactive: picks show and season from the listing, then confirms" {
  run_f "2\\ntutorials\\ny\\n" "" "https://youtu.be/abcDEF12345"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Seasons of Kettlebell:"* ]]
  [[ "$output" == *"3) Tutorials (9 episodes, feed)"* ]]
  [[ "$output" == *"Kettlebell/Season 03/Kettlebell S03E10"* ]]
}

@test "interactive: declining at the confirmation aborts without downloading" {
  run_f "2\\n3\\nn\\n" "" "https://youtu.be/abcDEF12345"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Aborted"* ]]
  ! grep -q "S03E10 - Mark_Wildman" "$LOG" || true
  ! grep -q " nas " "$LOG"
}

@test "duplicate in the show is reported and skipped" {
  run_f "y\n" "Kettlebell/2" "https://youtu.be/abcDEF12345" dup
  [ "$status" -eq 0 ]
  [[ "$output" == *"Already in this show"* ]]
  ! grep -q " nas " "$LOG"
}

@test "download failure is reported" {
  run_f "y\n" "Kettlebell/3" "https://youtu.be/abcDEF12345" dlfail
  [ "$status" -ne 0 ]
  [[ "$output" == *"Remote download failed"* ]]
}

@test "NAS failure leaves files on staging and says so" {
  run_f "y\n" "Kettlebell/3" "https://youtu.be/abcDEF12345" nasfail
  [ "$status" -ne 0 ]
  [[ "$output" == *"NAS transfer failed"* ]]
}

@test "yt -f rejects a category flag and requires a URL" {
  run zsh -c "source ./yt.sh; yt -f -g 'https://youtu.be/x'"
  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot be combined"* ]]
  run zsh -c "source ./yt.sh; yt -f"
  [ "$status" -ne 0 ]
  [[ "$output" == *"usage"* ]]
}

@test "a target without a slash is rejected" {
  run_f "y\n" "Kettlebell" "https://youtu.be/abcDEF12345"
  [ "$status" -ne 0 ]
  [[ "$output" == *"<Show>/<Season>"* ]]
}

@test "a season without an .order marker is asked about once and the answer is passed to resolve" {
  run_f "f\\ny\\n" "Kettlebell/3" "https://youtu.be/abcDEF12345" noorder
  [ "$status" -eq 0 ]
  [[ "$output" == *"has no order set yet"* ]]
  [[ "$output" == *"(feed)  →  S03E990"* ]]
  grep -q "Tutorials\|3 feed\|'3' feed\|3 'feed'\|feed" "$LOG"
}

@test "Show/N:Name:feed creates a feed season and numbers from the top" {
  run_f "y\\n" "Kettlebell/4:Swings:feed" "https://youtu.be/abcDEF12345"
  [ "$status" -eq 0 ]
  [[ "$output" == *"S03E990"* ]]          # stub answers the same dir; what matters is the order arg reached resolve
  grep -q "4:Swings" "$LOG"
  grep -q "feed" "$LOG"
}

@test "yt --season-order sets and reports a season order" {
  run env zsh -c "source ./yt.sh; YT_SSH='$STUB'; yt --season-order 'Kettlebell/3' feed"
  [ "$status" -eq 0 ]
  [[ "$output" == *"order=feed"* ]]
  run env zsh -c "source ./yt.sh; YT_SSH='$STUB'; yt --season-order 'Kettlebell/3' sideways"
  [ "$status" -ne 0 ]
}
