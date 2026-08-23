#!/usr/bin/env bats

# jellyfin_nfo.py: writes the episode .nfo, names the thumbnail, cleans the description.

setup() {
  cd "$BATS_TEST_DIRNAME/.."
  S="$BATS_TEST_TMPDIR/staging"
  mkdir -p "$S"
  stem="Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345]"
  : > "$S/$stem.mkv"
  : > "$S/$stem.jpg"
  cat > "$S/$stem.info.json" <<'JSON'
{"id": "abcDEF12345", "title": "Kettlebell Snatch Technique", "uploader": "Mark Wildman",
 "upload_date": "20200214",
 "description": "Shop Wildman Athletica: https://bit.ly/x\nFollow me on Instagram: http://bit.ly/y\n\nIf it HURTS, you're doing it WRONG. The snatch is a hinge first and a press never.\n\nFAQ & ANSWERS:\nWhat workout gear do you use?\n— Kettlebells: http://kettlebellkings.com/#_l_8t"}
JSON
}

@test "writes nfo with numbers, title, cleaned plot, aired, uniqueid; renames thumb; drops info.json" {
  run python3 jellyfin_nfo.py "$S" "Kettlebell" 3 10
  [ "$status" -eq 0 ]
  nfo="$S/Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345].nfo"
  [ -f "$nfo" ]
  grep -q "<title>Kettlebell Snatch Technique</title>" "$nfo"
  grep -q "<showtitle>Kettlebell</showtitle>" "$nfo"
  grep -q "<season>3</season>" "$nfo"
  grep -q "<episode>10</episode>" "$nfo"
  grep -q "<aired>2020-02-14</aired>" "$nfo"
  grep -q 'uniqueid type="YoutubeMetadata" default="true">abcDEF12345<' "$nfo"
  grep -q "Mark Wildman · 14 Feb 2020" "$nfo"
  grep -q "If it HURTS" "$nfo"
  ! grep -q "bit.ly" "$nfo"
  ! grep -q "Instagram" "$nfo"
  ! grep -q "kettlebellkings" "$nfo"
  [ -f "$S/Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345]-thumb.jpg" ]
  [ ! -f "$S/Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345].jpg" ]
  [ ! -f "$S/Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345].info.json" ]
}

@test "works without an info.json (title from filename, no plot body)" {
  rm "$S"/*.info.json
  run python3 jellyfin_nfo.py "$S" "Kettlebell" 3 10
  [ "$status" -eq 0 ]
  grep -q "<title>Mark_Wildman-Snatch-\[abcDEF12345\]</title>" "$S"/*.nfo
  grep -q "abcDEF12345" "$S"/*.nfo
}

@test "usage error on wrong arguments" {
  run python3 jellyfin_nfo.py "$S"
  [ "$status" -eq 2 ]
}
