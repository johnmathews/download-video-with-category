"""jellyfin_nfo.py: writes the episode .nfo, names the thumbnail, cleans the description.

It must also keep working as a standalone stdlib-only script piped to `python3 -` on the media VM.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from yt import jellyfin_nfo
from yt.jellyfin_nfo import clean_overview, episode_nfo, write_sidecars

STEM = "Kettlebell S03E10 - Mark_Wildman-Snatch-[abcDEF12345]"
INFO = {
    "id": "abcDEF12345",
    "title": "Kettlebell Snatch Technique",
    "uploader": "Mark Wildman",
    "upload_date": "20200214",
    "description": (
        "Shop Wildman Athletica: https://bit.ly/x\nFollow me on Instagram: http://bit.ly/y\n\n"
        "If it HURTS, you're doing it WRONG. The snatch is a hinge first and a press never.\n\n"
        "FAQ & ANSWERS:\nWhat workout gear do you use?\n— Kettlebells: http://kettlebellkings.com/#_l_8t"
    ),
}


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    (tmp_path / f"{STEM}.mkv").touch()
    (tmp_path / f"{STEM}.jpg").touch()
    (tmp_path / f"{STEM}.info.json").write_text(json.dumps(INFO))
    return tmp_path


def test_write_sidecars(staging: Path) -> None:
    written = write_sidecars(staging, "Kettlebell", 3, 10)
    nfo = staging / f"{STEM}.nfo"
    assert written == [nfo]
    text = nfo.read_text()
    assert "<title>Kettlebell Snatch Technique</title>" in text
    assert "<showtitle>Kettlebell</showtitle>" in text
    assert "<season>3</season>" in text
    assert "<episode>10</episode>" in text
    assert "<aired>2020-02-14</aired>" in text
    assert "<year>2020</year>" in text
    assert '<uniqueid type="YoutubeMetadata" default="true">abcDEF12345</uniqueid>' in text
    assert "Mark Wildman · 14 Feb 2020" in text
    assert "If it HURTS" in text
    for junk in ("bit.ly", "Instagram", "kettlebellkings"):
        assert junk not in text
    assert (staging / f"{STEM}-thumb.jpg").exists()
    assert not (staging / f"{STEM}.jpg").exists()
    assert not (staging / f"{STEM}.info.json").exists()


def test_without_info_json_title_from_filename(staging: Path) -> None:
    (staging / f"{STEM}.info.json").unlink()
    write_sidecars(staging, "Kettlebell", 3, 10)
    text = (staging / f"{STEM}.nfo").read_text()
    assert "<title>Mark_Wildman-Snatch-[abcDEF12345]</title>" in text
    assert "abcDEF12345" in text
    assert "<plot>" not in text


def test_multiple_videos_get_consecutive_episodes(staging: Path) -> None:
    (staging / "Kettlebell S03E10 - second-[zzzzzzzzzzz].mkv").touch()
    write_sidecars(staging, "Kettlebell", 3, 10)
    nfos = sorted(p.read_text() for p in staging.glob("*.nfo"))
    assert any("<episode>10</episode>" in n for n in nfos)
    assert any("<episode>11</episode>" in n for n in nfos)


def test_episode_nfo_escapes_xml() -> None:
    text = episode_nfo("A & B <c>", "Show", 1, 2, None, None, None, None, None)
    assert "<title>A &amp; B &lt;c&gt;</title>" in text
    assert "<plot>" not in text
    assert "<studio>" not in text


class TestCleanOverview:
    def test_header_only_when_no_prose(self) -> None:
        assert clean_overview("Follow me: http://x.com\n#tag", "Chan", "20240102") == "Chan · 2 Jan 2024"

    def test_keeps_first_real_paragraph(self) -> None:
        raw = "SUBSCRIBE NOW\n\nThis is a genuinely useful description of the workout. It explains the moves in detail."
        out = clean_overview(raw, None, None)
        assert out.startswith("This is a genuinely useful description")

    def test_truncates_at_sentence(self) -> None:
        raw = ("A sentence that is long enough to count as prose here. " * 20).strip()
        out = clean_overview(raw, None, None, limit=200)
        assert len(out) <= 200
        assert out.endswith(".")

    def test_bad_date_ignored(self) -> None:
        assert clean_overview("", "Chan", "2024") == "Chan"
        assert clean_overview("", "Chan", "20241350") == "Chan"


def test_main_usage_error() -> None:
    assert jellyfin_nfo.main(["prog"]) == 2


def test_main_not_a_directory(tmp_path: Path) -> None:
    assert jellyfin_nfo.main(["prog", str(tmp_path / "nope"), "S", "1", "1"]) == 1


def test_runs_standalone_over_stdin_like_on_the_media_vm(staging: Path) -> None:
    script = Path(jellyfin_nfo.__file__).read_text()
    result = subprocess.run(
        [sys.executable, "-", str(staging), "Kettlebell", "3", "10"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(f"{STEM}.nfo")
    assert "import yt" not in script  # must stay stdlib-only and self-contained
