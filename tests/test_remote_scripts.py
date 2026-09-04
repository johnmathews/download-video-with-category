"""The remote bash scripts, run for real under bash against a temp tree.

These cover what `FakeSSH` structurally cannot: `FakeSSH` matches on command text
and returns a canned tuple, so it verifies which script was chosen and how its
arguments were quoted, and nothing about what the script does. Every test here
runs the actual script — the same text that is piped to the media VM and the NAS
— with the real `rsync` and a fake `yt-dlp`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from yt.remote_scripts import (
    FITNESS_ITEM_SCRIPT,
    FITNESS_LIST_SCRIPT,
    FITNESS_RESOLVE_SCRIPT,
    NAS_SCRIPT,
    SINGLE_ITEM_SCRIPT,
)

from .conftest import requires_remote_tools

pytestmark = requires_remote_tools

Runner = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def fitness_base(tmp_path: Path) -> Path:
    """The fitness tree, kept out of tmp_path's root so the fake-bin dir is not seen as a show."""
    base = tmp_path / "fitness"
    base.mkdir()
    return base


def _season(show_dir: Path, number: int, *, title: str = "", order: str = "", episodes: tuple[str, ...] = ()) -> Path:
    season = show_dir / f"Season {number:02d}"
    season.mkdir(parents=True)
    if title:
        (season / "season.nfo").write_text(f"<season>\n  <title>{title}</title>\n</season>\n")
    if order:
        (season / ".order").write_text(f"{order}\n")
    for name in episodes:
        (season / name).write_text("video\n")
    return season


# ---------------------------------------------------------------------------
# NAS_SCRIPT — stage 2. The direction of this rsync is the highest-stakes
# assertion in the suite: reversed, it moves the finished library back into
# staging and deletes it from tank.
# ---------------------------------------------------------------------------


class TestNasScript:
    def test_moves_staged_files_into_final_dir(self, run_remote: Runner, tmp_path: Path) -> None:
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "video.mkv").write_text("payload")
        final = tmp_path / "final"

        result = run_remote(NAS_SCRIPT, staging, final)

        assert result.returncode == 0, result.stderr
        assert (final / "video.mkv").read_text() == "payload"
        assert not (staging / "video.mkv").exists()
        assert not staging.exists(), "staging dir should be rmdir'd once emptied"

    def test_leaves_existing_library_files_untouched(self, run_remote: Runner, tmp_path: Path) -> None:
        """The guard against a reversed rsync: everything already in the final dir survives."""
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "new.mkv").write_text("new")
        final = tmp_path / "final"
        final.mkdir()
        (final / "already-here.mkv").write_text("precious")

        result = run_remote(NAS_SCRIPT, staging, final)

        assert result.returncode == 0, result.stderr
        assert (final / "already-here.mkv").read_text() == "precious"
        assert (final / "new.mkv").read_text() == "new"

    def test_missing_staging_dir_exits_1(self, run_remote: Runner, tmp_path: Path) -> None:
        result = run_remote(NAS_SCRIPT, tmp_path / "nope", tmp_path / "final")
        assert result.returncode == 1
        assert "Staging dir not found" in result.stderr


# ---------------------------------------------------------------------------
# SINGLE_ITEM_SCRIPT — stage 1 for `yt -<category> URL`.
#   $1 tmpdir  $2 cookie  $3 staging_dir  $4 url
# ---------------------------------------------------------------------------


class TestSingleItemScript:
    @pytest.fixture
    def dirs(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        staging = tmp_path / "staging"
        cookie = tmp_path / "cookies.txt"
        cookie.write_text("cookie\n")
        return tmpdir, cookie, staging

    def test_stages_video_and_prints_basename(self, run_remote: Runner, dirs: tuple[Path, Path, Path]) -> None:
        tmpdir, cookie, staging = dirs
        result = run_remote(SINGLE_ITEM_SCRIPT, tmpdir, cookie, staging, "https://fake/url")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "Uploader-Some_Video-[abcDEF12345].mkv"
        assert (staging / "Uploader-Some_Video-[abcDEF12345].mkv").exists()

    def test_passes_the_cookie_to_ytdlp(
        self, run_remote: Runner, dirs: tuple[Path, Path, Path], ytdlp_calls: Callable[[], list[str]]
    ) -> None:
        tmpdir, cookie, staging = dirs
        run_remote(SINGLE_ITEM_SCRIPT, tmpdir, cookie, staging, "https://fake/url")

        calls = ytdlp_calls()
        assert calls, "yt-dlp was never invoked"
        assert f"--cookies {cookie}" in calls[0]

    def test_drops_sidecar_images_and_subtitles(self, run_remote: Runner, dirs: tuple[Path, Path, Path]) -> None:
        """Loose images bleed into Jellyfin's folder art; subs are already embedded."""
        tmpdir, cookie, staging = dirs
        files = "Uploader-Some_Video-[abcDEF12345].mkv:Uploader-Some_Video-[abcDEF12345].jpg:Uploader-Some_Video-[abcDEF12345].srt"
        result = run_remote(SINGLE_ITEM_SCRIPT, tmpdir, cookie, staging, "https://fake/url", FAKE_YTDLP_FILES=files)

        assert result.returncode == 0, result.stderr
        staged = {p.name for p in staging.iterdir()}
        assert staged == {"Uploader-Some_Video-[abcDEF12345].mkv"}

    def test_no_video_exits_2(self, run_remote: Runner, dirs: tuple[Path, Path, Path]) -> None:
        tmpdir, cookie, staging = dirs
        result = run_remote(SINGLE_ITEM_SCRIPT, tmpdir, cookie, staging, "https://fake/url", FAKE_YTDLP_MODE="skip")
        assert result.returncode == 2
        assert "No video files found" in result.stderr

    def test_retries_without_subtitles_when_first_attempt_yields_nothing(
        self, run_remote: Runner, dirs: tuple[Path, Path, Path], ytdlp_calls: Callable[[], list[str]]
    ) -> None:
        tmpdir, cookie, staging = dirs
        result = run_remote(SINGLE_ITEM_SCRIPT, tmpdir, cookie, staging, "https://fake/url", FAKE_YTDLP_FAIL_FIRST="1")

        assert result.returncode == 0, result.stderr
        assert "Retrying without subtitles" in result.stderr
        calls = ytdlp_calls()
        assert len(calls) == 2
        assert "--write-subs" in calls[0]
        assert "--write-subs" not in calls[1], "the retry must drop the subtitle flags"


# ---------------------------------------------------------------------------
# FITNESS_RESOLVE_SCRIPT — stage 0.
#   $1 base  $2 show  $3 spec  $4 order
# stdout, 6 lines: show_dir, season_dir, next episode, digits, order, order_missing
# ---------------------------------------------------------------------------


class TestFitnessResolveScript:
    def test_existing_season_by_number_returns_the_six_line_contract(
        self, run_remote: Runner, fitness_base: Path
    ) -> None:
        show = fitness_base / "Kettlebell"
        season = _season(show, 3, title="Tutorials", order="course", episodes=("Kettlebell S03E01 - a.mkv",))

        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Kettlebell", "3", "")

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [str(show), str(season), "2", "2", "course", "0"]

    def test_existing_season_by_nfo_title_is_case_insensitive(self, run_remote: Runner, fitness_base: Path) -> None:
        show = fitness_base / "Kettlebell"
        season = _season(show, 3, title="Tutorials", order="course")

        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Kettlebell", "tutorials", "")

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[1] == str(season)

    def test_course_order_takes_the_next_number_after_the_highest(self, run_remote: Runner, fitness_base: Path) -> None:
        show = fitness_base / "Kettlebell"
        _season(
            show,
            1,
            order="course",
            episodes=("Kettlebell S01E01 - a.mkv", "Kettlebell S01E02 - b.mkv", "Kettlebell S01E03 - c.mkv"),
        )

        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Kettlebell", "1", "")

        assert result.stdout.splitlines()[2] == "4"

    def test_feed_order_counts_down_from_the_lowest(self, run_remote: Runner, fitness_base: Path) -> None:
        show = fitness_base / "Mobility"
        _season(show, 1, order="feed", episodes=("Mobility S01E983 - a.mkv",))

        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Mobility", "1", "")

        lines = result.stdout.splitlines()
        assert lines[2] == "982", "feed seasons number DOWN from 999"
        assert lines[3] == "3", "feed seasons are three digits wide"
        assert lines[4] == "feed"

    def test_empty_feed_season_starts_at_999(self, run_remote: Runner, fitness_base: Path) -> None:
        _season(fitness_base / "Mobility", 1, order="feed")
        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Mobility", "1", "")
        assert result.stdout.splitlines()[2] == "999"

    def test_missing_order_marker_is_reported(self, run_remote: Runner, fitness_base: Path) -> None:
        _season(fitness_base / "Kettlebell", 1)
        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Kettlebell", "1", "")
        lines = result.stdout.splitlines()
        assert lines[4] == "course"
        assert lines[5] == "1", "a season with no .order must report order_missing=1"

    def test_creates_show_and_season_with_nfos(self, run_remote: Runner, fitness_base: Path) -> None:
        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Running", "1:Form", "")

        assert result.returncode == 0, result.stderr
        show = fitness_base / "Running"
        season = show / "Season 01"
        assert (show / "tvshow.nfo").exists()
        assert "<title>Running</title>" in (show / "tvshow.nfo").read_text()
        assert "<title>Form</title>" in (season / "season.nfo").read_text()
        assert "<seasonnumber>1</seasonnumber>" in (season / "season.nfo").read_text()

    def test_xml_special_characters_are_escaped_in_new_nfos(self, run_remote: Runner, fitness_base: Path) -> None:
        run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Mobility & Physio", "1:Warm & Up", "")
        assert "<title>Mobility &amp; Physio</title>" in (fitness_base / "Mobility & Physio" / "tvshow.nfo").read_text()

    def test_unknown_season_without_create_name_exits_4(self, run_remote: Runner, fitness_base: Path) -> None:
        _season(fitness_base / "Kettlebell", 1)
        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Kettlebell", "9", "")
        assert result.returncode == 4
        assert "No season" in result.stderr

    def test_bad_order_value_exits_5(self, run_remote: Runner, fitness_base: Path) -> None:
        _season(fitness_base / "Kettlebell", 1)
        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Kettlebell", "1", "sideways")
        assert result.returncode == 5
        assert "order must be feed or course" in result.stderr

    def test_setting_the_order_writes_the_marker(self, run_remote: Runner, fitness_base: Path) -> None:
        season = _season(fitness_base / "Kettlebell", 1)
        result = run_remote(FITNESS_RESOLVE_SCRIPT, fitness_base, "Kettlebell", "1", "feed")
        assert result.returncode == 0, result.stderr
        assert (season / ".order").read_text().strip() == "feed"


# ---------------------------------------------------------------------------
# FITNESS_LIST_SCRIPT — discovery.
# stdout: "<show>\t<season number>\t<title>\t<episode count>\t<order>"
# ---------------------------------------------------------------------------


class TestFitnessListScript:
    def test_reports_number_title_count_and_order_in_that_column_order(
        self, run_remote: Runner, fitness_base: Path
    ) -> None:
        _season(
            fitness_base / "Kettlebell",
            3,
            title="Tutorials",
            order="feed",
            episodes=("a.mkv", "b.mkv"),
        )

        result = run_remote(FITNESS_LIST_SCRIPT, fitness_base)

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["Kettlebell\t3\tTutorials\t2\tfeed"]

    def test_show_without_seasons_gets_the_empty_row(self, run_remote: Runner, fitness_base: Path) -> None:
        (fitness_base / "Rowing").mkdir()
        result = run_remote(FITNESS_LIST_SCRIPT, fitness_base)
        assert result.stdout.splitlines() == ["Rowing\t\t\t0\t"]

    def test_season_without_order_marker_defaults_to_course(self, run_remote: Runner, fitness_base: Path) -> None:
        _season(fitness_base / "Kettlebell", 1, title="Basics")
        result = run_remote(FITNESS_LIST_SCRIPT, fitness_base)
        assert result.stdout.splitlines() == ["Kettlebell\t1\tBasics\t0\tcourse"]

    def test_unescapes_xml_entities_in_season_titles(self, run_remote: Runner, fitness_base: Path) -> None:
        _season(fitness_base / "Mobility", 1, title="Physio &amp; Rehab")
        result = run_remote(FITNESS_LIST_SCRIPT, fitness_base)
        assert result.stdout.splitlines() == ["Mobility\t1\tPhysio & Rehab\t0\tcourse"]

    def test_exits_zero_even_when_the_last_show_has_seasons(self, run_remote: Runner, fitness_base: Path) -> None:
        """Regression: an earlier version left $? at 1 here and the caller discarded the listing."""
        _season(fitness_base / "Kettlebell", 1, title="Basics")
        result = run_remote(FITNESS_LIST_SCRIPT, fitness_base)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# FITNESS_ITEM_SCRIPT — stage 1 for `yt -f`.
#   $1 tmpdir $2 cookie $3 staging $4 url $5 show $6 season $7 episode $8 digits
# ---------------------------------------------------------------------------


class TestFitnessItemScript:
    @pytest.fixture
    def dirs(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        tmpdir = tmp_path / "tmp"
        tmpdir.mkdir()
        staging = tmp_path / "staging"
        cookie = tmp_path / "cookies.txt"
        cookie.write_text("cookie\n")
        return tmpdir, cookie, staging

    def test_renames_video_and_sidecars_with_the_snnenn_prefix(
        self, run_remote: Runner, dirs: tuple[Path, Path, Path]
    ) -> None:
        tmpdir, cookie, staging = dirs
        files = "Uploader-Clip-[abc123].mkv:Uploader-Clip-[abc123].jpg:Uploader-Clip-[abc123].info.json"

        result = run_remote(
            FITNESS_ITEM_SCRIPT,
            tmpdir,
            cookie,
            staging,
            "https://fake/url",
            "Kettlebell",
            "3",
            "7",
            "2",
            FAKE_YTDLP_FILES=files,
        )

        assert result.returncode == 0, result.stderr
        staged = sorted(p.name for p in staging.iterdir())
        assert staged == [
            "Kettlebell S03E07 - Uploader-Clip-[abc123].info.json",
            "Kettlebell S03E07 - Uploader-Clip-[abc123].jpg",
            "Kettlebell S03E07 - Uploader-Clip-[abc123].mkv",
        ]
        assert result.stdout.strip() == "Kettlebell S03E07 - Uploader-Clip-[abc123].mkv"

    def test_three_digit_width_is_honoured_for_feed_seasons(
        self, run_remote: Runner, dirs: tuple[Path, Path, Path]
    ) -> None:
        tmpdir, cookie, staging = dirs
        result = run_remote(
            FITNESS_ITEM_SCRIPT,
            tmpdir,
            cookie,
            staging,
            "https://fake/url",
            "Mobility",
            "1",
            "983",
            "3",
            FAKE_YTDLP_FILES="Uploader-Clip-[abc123].mkv",
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "Mobility S01E983 - Uploader-Clip-[abc123].mkv"

    def test_loose_subtitle_sidecars_never_reach_staging(
        self, run_remote: Runner, dirs: tuple[Path, Path, Path]
    ) -> None:
        tmpdir, cookie, staging = dirs
        files = "Uploader-Clip-[abc123].mkv:Uploader-Clip-[abc123].en.srv3:Uploader-Clip-[abc123].en.ttml"

        result = run_remote(
            FITNESS_ITEM_SCRIPT,
            tmpdir,
            cookie,
            staging,
            "https://fake/url",
            "Kettlebell",
            "1",
            "1",
            "2",
            FAKE_YTDLP_FILES=files,
        )

        assert result.returncode == 0, result.stderr
        assert sorted(p.suffix for p in staging.iterdir()) == [".mkv"]

    def test_removes_the_cookie_and_tmpdir_on_success(self, run_remote: Runner, dirs: tuple[Path, Path, Path]) -> None:
        tmpdir, cookie, staging = dirs
        result = run_remote(
            FITNESS_ITEM_SCRIPT, tmpdir, cookie, staging, "https://fake/url", "Kettlebell", "1", "1", "2"
        )
        assert result.returncode == 0, result.stderr
        assert not cookie.exists()
        assert not tmpdir.exists()
