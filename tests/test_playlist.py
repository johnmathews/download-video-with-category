"""Playlist mode: the orchestration against the fake ssh, plus the item script run for real under bash."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from yt.playlist import download_playlist, slugify
from yt.remote_scripts import PLAYLIST_ITEM_SCRIPT
from yt.ui import Failure

from .conftest import requires_remote_tools

Runner = Callable[..., subprocess.CompletedProcess[str]]

URL = "https://www.youtube.com/playlist?list=PLtest"


class TestSlugify:
    @pytest.mark.parametrize(
        ("raw", "slug"),
        [
            ("My Cooking Series", "my-cooking-series"),
            ("Hello, World! (2024)", "hello-world-2024"),
            ("  /Trip — Italy/  ", "trip-italy"),
            ("Café Música", "caf-m-sica"),
            ("", ""),
        ],
    )
    def test_slug(self, raw: str, slug: str) -> None:
        assert slugify(raw) == slug


@pytest.fixture
def media(fake_ssh: Any, cookies: Path, answers: Callable[[str], None]) -> Any:
    counter = {"n": 0}

    def mktemp(call: Any) -> tuple[int, str] | None:
        if "mktemp -d" in call.command:
            counter["n"] += 1
            return 0, f"/tmp/yt.stub{counter['n']}\n"
        return None

    fake_ssh.when(mktemp)
    fake_ssh.on("playlist_title", stdout="Test Playlist\n")
    fake_ssh.on("playlist_index", stdout="3\n")
    fake_ssh.on("bash -s", host="media", stdout="001-fake-[id].mkv\n")
    answers("y\n")
    return fake_ssh


def test_downloads_every_item(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert download_playlist(URL) == 0
    out, err = capsys.readouterr()
    assert "downloaded 3, skipped 0, failed 0" in err
    assert media.count("bash -s", host="media") == 3
    assert media.count("bash -s", host="nas") == 3
    assert out.count("/mnt/nfs/movies/youtube/test-playlist/001-fake-[id].mkv\n") == 3
    item = next(c for c in media.calls if c.host == "media" and c.command.startswith("bash -s"))
    assert item.command.endswith(f"'{URL}' 1 /mnt/nfs/movies/youtube/test-playlist/archive.txt")
    nas = next(c for c in media.calls if c.host == "nas")
    assert nas.command == "bash -s -- /mnt/swift/downloads/yt-staging/yt.stub2 /mnt/tank/movies/youtube/test-playlist"


def test_freeform_answer_overrides_slug(
    media: Any, answers: Callable[[str], None], capsys: pytest.CaptureFixture[str]
) -> None:
    answers("Holiday 2024!\n")
    download_playlist(URL)
    assert "/mnt/nfs/movies/youtube/holiday-2024/" in capsys.readouterr().out


def test_n_aborts_before_downloading(media: Any, answers: Callable[[str], None]) -> None:
    answers("n\n")
    with pytest.raises(Failure):
        download_playlist(URL)
    assert media.count("bash -s") == 0
    assert media.commands()[-1] == "rm -rf /tmp/yt.stub1 2>/dev/null || true"


def test_all_items_skipped_is_success(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules = [r for r in media.rules if r.__name__ == "mktemp"]
    media.on("playlist_title", stdout="Test Playlist\n")
    media.on("playlist_index", stdout="3\n")
    media.on("bash -s", host="media", stdout="")
    assert download_playlist(URL) == 0
    assert "downloaded 0, skipped 3, failed 0" in capsys.readouterr().err
    assert media.count("bash -s", host="nas") == 0


def test_nas_failure_counts_failed_and_processes_all(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.on("bash -s", host="nas", rc=1)
    # a later rule must win over the generic media rule for nas calls: re-add nas rule first
    media.rules.insert(0, media.rules.pop())
    assert download_playlist(URL) == 1
    assert "failed 3" in capsys.readouterr().err
    assert media.count("bash -s", host="media") == 3


def test_ytdlp_failure_is_failed_not_skipped(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules = [r for r in media.rules if r.__name__ == "mktemp"]
    media.on("playlist_title", stdout="Test Playlist\n")
    media.on("playlist_index", stdout="3\n")
    media.on("bash -s", host="media", rc=3)
    assert download_playlist(URL) == 1
    err = capsys.readouterr().err
    assert "failed 3" in err
    assert "skipped 0" in err
    # each failed item's tmp + staging dirs were removed
    assert media.count("rm -rf /tmp/yt.stub2 /mnt/nfs/downloads/yt-staging/yt.stub2") == 1


def test_empty_playlist(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules = [r for r in media.rules if r.__name__ == "mktemp"]
    media.on("playlist_title", stdout="Empty\n")
    media.on("playlist_index", stdout="0\n")
    with pytest.raises(Failure):
        download_playlist(URL)
    assert "Playlist is empty" in capsys.readouterr().err


def test_missing_cookie_file(
    fake_ssh: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOCAL_YT_COOKIES", "/nope/cookies.txt")
    with pytest.raises(Failure):
        download_playlist(URL)
    assert "Cookies file not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The item script itself, run for real under bash (shared harness in conftest.py).
# ---------------------------------------------------------------------------

VIDEO = "001-fake-video-[abcd1234].mkv"


def _run_item_script(run_remote: Runner, tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    idir = tmp_path / "item"
    idir.mkdir()
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("fake\n")
    return run_remote(
        PLAYLIST_ITEM_SCRIPT,
        idir,
        cookie,
        tmp_path / "staging",
        "https://fake/url",
        "1",
        tmp_path / "archive.txt",
        **env,
    )


@requires_remote_tools
def test_item_script_success_emits_basename(run_remote: Runner, tmp_path: Path) -> None:
    result = _run_item_script(run_remote, tmp_path, FAKE_YTDLP_FILES=VIDEO)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VIDEO


@requires_remote_tools
def test_item_script_archived_skip(run_remote: Runner, tmp_path: Path) -> None:
    result = _run_item_script(run_remote, tmp_path, FAKE_YTDLP_MODE="skip")
    assert result.returncode == 0
    assert result.stdout == ""


@requires_remote_tools
def test_item_script_real_failure_exits_3(run_remote: Runner, tmp_path: Path) -> None:
    result = _run_item_script(run_remote, tmp_path, FAKE_YTDLP_MODE="fail")
    assert result.returncode == 3
    assert result.stdout == ""


def test_item_script_prefixes_embedded_title_with_index() -> None:
    # Both yt-dlp invocations (main + no-subs retry) must set meta_title so Jellyfin's
    # metadata "Name" sort matches playlist order.
    assert PLAYLIST_ITEM_SCRIPT.count('--parse-metadata "%(playlist_index)03d - %(title)s:%(meta_title)s"') == 2
