from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from yt import cli
from yt.cli import help_text, main, run


def _run(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    return int(exc.value.code or 0)


class TestHelp:
    def test_no_args_prints_help_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run([]) == 0
        out, err = capsys.readouterr()
        assert out == ""
        assert "CATEGORIES:" in err

    @pytest.mark.parametrize("argv", [["--help"], ["help"]])
    def test_help_flag_and_word(self, argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(argv) == 0
        out, err = capsys.readouterr()
        assert out == ""
        assert "USAGE:" in err

    def test_help_lists_every_category(self) -> None:
        text = help_text()
        for flag, name in [("y", "youtube"), ("h", "humanity"), ("e", "math+engineering")]:
            assert f"-{flag}  {name}" in text


class TestCategoryDispatch:
    @pytest.mark.parametrize(
        ("argv", "category"),
        [
            (["-y", "https://youtu.be/x"], "youtube"),
            (["-c", "https://youtu.be/x"], "create"),
            (["-m", "https://youtu.be/x"], "music"),
            (["-h", "https://youtu.be/x"], "humanity"),
            (["-t", "https://youtu.be/x"], "travel"),
            (["-e", "https://youtu.be/x"], "math+engineering"),
            (["--category", "music", "https://youtu.be/x"], "music"),
            (["https://youtu.be/x", "-y"], "youtube"),
        ],
    )
    def test_maps_flag_to_category(self, argv: list[str], category: str) -> None:
        with patch("yt.single.download_single", return_value=0) as dl:
            assert run(argv) == 0
        dl.assert_called_once_with(category, "https://youtu.be/x")

    def test_missing_category(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["https://youtu.be/x"]) == 1
        assert "Category shortcut is required" in capsys.readouterr().err

    def test_invalid_category(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["--category", "bogus", "https://youtu.be/x"]) == 1
        err = capsys.readouterr().err
        assert "Invalid category 'bogus'" in err
        assert "youtube, create, music" in err

    def test_missing_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["-y"]) == 1
        assert "URL is required" in capsys.readouterr().err

    def test_unknown_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["--bogus", "x"]) == 1
        assert "Error" in capsys.readouterr().err


class TestPlaylistDispatch:
    def test_rejects_category_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["-p", "-t", "https://youtube.com/playlist?list=x"]) == 1
        assert "cannot be combined" in capsys.readouterr().err

    def test_requires_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["-p"]) == 1
        assert "playlist URL is required" in capsys.readouterr().err

    @pytest.mark.parametrize("flag", ["-p", "--playlist"])
    def test_dispatches(self, flag: str) -> None:
        with patch("yt.playlist.download_playlist", return_value=0) as dl:
            assert run([flag, "https://youtube.com/playlist?list=x"]) == 0
        dl.assert_called_once_with("https://youtube.com/playlist?list=x")


class TestFitnessDispatch:
    def test_rejects_category_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["-f", "-y", "https://youtu.be/x"]) == 1
        assert "cannot be combined" in capsys.readouterr().err

    def test_requires_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(["-f"]) == 1
        assert "usage" in capsys.readouterr().err

    def test_url_only_is_interactive(self) -> None:
        with patch("yt.fitness.add_to_show", return_value=0) as add:
            assert run(["-f", "https://youtu.be/x"]) == 0
        add.assert_called_once_with("", "https://youtu.be/x")

    def test_target_and_url(self) -> None:
        with patch("yt.fitness.add_to_show", return_value=0) as add:
            assert run(["--fitness", "Kettlebell/3", "https://youtu.be/x"]) == 0
        add.assert_called_once_with("Kettlebell/3", "https://youtu.be/x")

    def test_season_order(self) -> None:
        with patch("yt.fitness.season_order", return_value=0) as so:
            assert run(["--season-order", "Kettlebell/3", "feed"]) == 0
        so.assert_called_once_with("Kettlebell/3", "feed")
        with patch("yt.fitness.season_order", return_value=0) as so:
            run(["--season-order", "Kettlebell/3"])
        so.assert_called_once_with("Kettlebell/3", "")


class TestUpdate:
    def test_runs_installer_with_tty(self, fake_ssh: Any, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(["--update"]) == 0
        call = fake_ssh.calls[0]
        assert call.tty
        assert call.host == "media"
        assert "yt-dlp_linux" in call.command
        assert "/usr/local/bin/yt-dlp" in call.command
        assert "Updating yt-dlp" in capsys.readouterr().err


class TestMainExitCodes:
    def test_failure_message_and_code(self) -> None:
        from yt.ui import Failure

        with patch.object(cli, "run", side_effect=Failure("nope", 4)):
            assert _run(["-y", "u"]) == 4

    def test_keyboard_interrupt(self) -> None:
        with patch.object(cli, "run", side_effect=KeyboardInterrupt):
            assert _run(["-y", "u"]) == 130


class TestRetiredTrainingCategory:
    """`-g`/training filed gym videos flat into youtube/training/. `yt -f` supersedes
    it by filing them as Jellyfin Health & Fitness episodes, so -g is retired — but
    it stays intercepted, because it is in muscle memory and an argparse
    "unrecognized arguments" error would not tell anyone what to do instead."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["-g", "https://youtu.be/x"],
            ["https://youtu.be/x", "-g"],
            ["--category", "training", "https://youtu.be/x"],
        ],
    )
    def test_points_at_fitness_mode_and_fails(self, argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
        with patch("yt.single.download_single") as dl:
            assert _run(argv) == 1
        dl.assert_not_called()
        err = capsys.readouterr().err
        assert "retired" in err
        assert "yt -f" in err

    def test_says_the_old_directory_is_left_alone(self, capsys: pytest.CaptureFixture[str]) -> None:
        _run(["-g", "https://youtu.be/x"])
        assert "youtube/training/" in capsys.readouterr().err

    def test_training_is_no_longer_a_valid_category(self) -> None:
        from yt.config import CATEGORIES, VALID_CATEGORIES

        assert "training" not in VALID_CATEGORIES
        assert "g" not in CATEGORIES

    def test_help_no_longer_advertises_it(self) -> None:
        text = help_text()
        assert "-g  training" not in text
        assert "--category training" not in text
        # One mention survives on purpose: the note saying the old directory is legacy.
        mentions = [line for line in text.splitlines() if "training" in line]
        assert len(mentions) == 1 and "Legacy" in mentions[0], mentions

    def test_the_surviving_categories_still_dispatch(self) -> None:
        for flag, name in [("y", "youtube"), ("m", "music"), ("h", "humanity"), ("e", "math+engineering")]:
            with patch("yt.single.download_single", return_value=0) as dl:
                assert run([f"-{flag}", "https://youtu.be/x"]) == 0
            dl.assert_called_once_with(name, "https://youtu.be/x")
