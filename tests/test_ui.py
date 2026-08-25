from __future__ import annotations

import io
import sys

import pytest

from yt.ui import Elapsed, Failure, emit, format_size, info, prompt


class TestFormatSize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", "Unknown"),
            ("0", "Unknown"),
            ("NA", "Unknown"),
            (str(5 * 1048576 + 100000), "5.1 MB"),
            (str(99 * 1048576), "99.0 MB"),
            (str(347 * 1048576), "350 MB"),
            (str(1024 * 1048576), "1.0 GB"),
            (str(int(2.5 * 1073741824)), "2.5 GB"),
        ],
    )
    def test_rounding(self, raw: str, expected: str) -> None:
        assert format_size(raw) == expected


class TestElapsed:
    def test_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = iter([100.0, 145.0, 100.0 + 83.0])
        monkeypatch.setattr("yt.ui.time.monotonic", lambda: next(clock))
        elapsed = Elapsed()
        assert str(elapsed) == "45s"
        assert str(elapsed) == "1m 23s"


class TestStreams:
    def test_info_goes_to_stderr_and_emit_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        info("status")
        emit("/path")
        out, err = capsys.readouterr()
        assert out == "/path\n"
        assert err == "status\n"

    def test_prompt_reads_a_line_and_returns_none_on_eof(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
        assert prompt("Q? ") == "yes"
        assert prompt("Q? ") is None
        assert capsys.readouterr().err == "Q? Q? "


def test_failure_defaults() -> None:
    assert Failure().code == 1
    assert Failure("boom", 3).message == "boom"
