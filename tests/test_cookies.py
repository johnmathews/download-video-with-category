from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from yt.cookies import check_cookies, check_ytdlp_installed, upload_cookies
from yt.ui import Failure


def test_missing_cookie_file_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("LOCAL_YT_COOKIES", "/nope/cookies.txt")
    with pytest.raises(Failure):
        check_cookies()
    assert "Cookies file not found" in capsys.readouterr().err


def test_empty_cookie_file_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "c.txt"
    path.touch()
    monkeypatch.setenv("LOCAL_YT_COOKIES", str(path))
    with pytest.raises(Failure):
        check_cookies()
    assert "Cookies file is empty" in capsys.readouterr().err


def test_fresh_cookie_ok_no_warning(cookies: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check_cookies() == cookies
    assert capsys.readouterr().err == ""


def test_stale_cookie_warns(cookies: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = time.time() - 10 * 86400
    os.utime(cookies, (old, old))
    check_cookies()
    assert "10 days old" in capsys.readouterr().err


def test_default_cookie_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_YT_COOKIES", raising=False)
    from yt.config import cookies_path

    assert cookies_path() == Path.home() / ".config/yt-dlp/cookies/cookies.txt"


def test_ytdlp_missing(fake_ssh, capsys: pytest.CaptureFixture[str]) -> None:
    fake_ssh.on("command -v yt-dlp", rc=1)
    with pytest.raises(Failure):
        check_ytdlp_installed()
    assert "yt-dlp not found" in capsys.readouterr().err


def test_upload_streams_file_with_umask(fake_ssh, cookies: Path) -> None:
    assert upload_cookies(cookies, "/tmp/yt.x/cookies.txt")
    call = fake_ssh.calls[0]
    assert call.command == "umask 077 && cat > /tmp/yt.x/cookies.txt"
    assert call.stdin == "fake-cookie\n"
