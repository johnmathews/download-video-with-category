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
    fake_ssh.on("playlist_index", stdout="1\n2\n3\n")  # yt-dlp prints one index per entry
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
    media.on("playlist_index", stdout="1\n2\n3\n")
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
    media.on("playlist_index", stdout="1\n2\n3\n")
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
    media.on("playlist_index", stdout="")  # yt-dlp prints nothing for a playlist with no entries
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


class TestStagingLifecycle:
    """CLAUDE.md: staging is kept for manual recovery after a NAS failure, and
    removed otherwise. Both directions need pinning — a refactor that tidies up
    the keep-paths destroys a fully downloaded episode."""

    def test_nas_failure_keeps_every_staged_item_for_recovery(
        self, media: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        media.rules.insert(0, lambda c: (1, "") if c.host == "nas" else None)

        assert download_playlist(URL) == 1
        err = capsys.readouterr().err
        assert "failed 3" in err

        removed = " ".join(c for c in media.commands() if c.startswith("rm -rf"))
        for n in (2, 3, 4):
            assert f"/mnt/nfs/downloads/yt-staging/yt.stub{n}" not in removed, (
                "staging must survive a NAS failure so the files can be recovered by hand"
            )
        assert "files remain on SSD" in err


@requires_remote_tools
def test_item_script_archived_skip_removes_its_own_staging_dir(run_remote: Runner, tmp_path: Path) -> None:
    """The script mkdir -p's the staging dir before it knows the item is archived.
    Re-running a fully archived playlist is the normal way to top one up, so a dir
    left behind per item accumulates forever — and destroys the signal that anything
    still in yt-staging needs manual recovery."""
    idir = tmp_path / "item"
    idir.mkdir()
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("fake\n")
    staging = tmp_path / "staging"

    result = run_remote(
        PLAYLIST_ITEM_SCRIPT,
        idir,
        cookie,
        staging,
        "https://fake/url",
        "1",
        tmp_path / "archive.txt",
        FAKE_YTDLP_MODE="skip",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not staging.exists(), "archived skip left its staging dir behind"
    assert not idir.exists(), "archived skip left its tmp dir behind"


class TestPlaylistCount:
    """`yt-dlp … | wc -l` reports wc's exit status, which is always 0. A listing that
    died at item 50 of 200 was indistinguishable from a 200-item playlist that really
    had 50 entries: yt downloaded 50, printed "downloaded 50, skipped 0, failed 0" and
    exited 0. The count==0 guard never fired, so nothing said anything was wrong."""

    def test_the_count_command_is_not_piped(self, media: Any) -> None:
        """A pipe would discard yt-dlp's exit code again. Pinning the shape, because the
        defect is invisible in the output — it only shows as a too-short playlist."""
        download_playlist(URL)
        command = next(c for c in media.commands() if "playlist_index" in c)
        assert "|" not in command, f"exit code discarded by a pipe: {command}"

    def test_a_failed_listing_aborts_instead_of_downloading_a_prefix(
        self, media: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        media.rules.insert(0, lambda c: (1, "1\n2\n") if "playlist_index" in c.command else None)

        with pytest.raises(Failure):
            download_playlist(URL)

        err = capsys.readouterr().err
        assert "Could not read the playlist" in err
        assert media.count("bash -s", host="media") == 0, "must not download a partial playlist"

    def test_an_empty_playlist_says_empty_not_unreadable(self, media: Any, capsys: pytest.CaptureFixture[str]) -> None:
        media.rules.insert(0, lambda c: (0, "") if "playlist_index" in c.command else None)

        with pytest.raises(Failure):
            download_playlist(URL)

        err = capsys.readouterr().err
        assert "empty" in err.lower()
        assert "Could not read" not in err

    def test_counts_the_printed_index_lines(self, media: Any, capsys: pytest.CaptureFixture[str]) -> None:
        media.rules.insert(0, lambda c: (0, "1\n2\n3\n4\n5\n") if "playlist_index" in c.command else None)
        assert download_playlist(URL) == 0
        assert "downloaded 5" in capsys.readouterr().err
