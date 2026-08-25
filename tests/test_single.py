"""Single-video mode against the fake ssh. Mirrors what the zsh path did call-for-call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from yt.single import download_single, warn_if_unsupported_url
from yt.ui import Failure

URL = "https://youtu.be/abcDEF12345"
FINAL = "/mnt/nfs/movies/youtube/training"


@pytest.fixture
def media(fake_ssh: Any, cookies: Path) -> Any:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    fake_ssh.on("--print '%(id)s'", stdout="abcDEF12345\nSome Video\n1080p\n2200000000\n")
    fake_ssh.on("bash -s", host="media", stdout="Uploader-Some_Video-[abcDEF12345].mkv\n")
    return fake_ssh


def test_happy_path(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert download_single("training", URL) == 0
    out, err = capsys.readouterr()
    assert out == f"{FINAL}/Uploader-Some_Video-[abcDEF12345].mkv\n"
    assert "📹 VIDEO: Some Video" in err
    assert "📦 Size: ~2.0 GB" in err
    assert "✓ No existing download found" in err
    assert "Successfully downloaded to: /mnt/nfs/movies/youtube/training" in err
    # cookie went up under umask 077, download script got quoted args, NAS stage-2 targeted the category dir
    assert media.count("umask 077 && cat > /tmp/yt.stub42/cookies.txt") == 1
    dl = next(c for c in media.calls if c.host == "media" and c.command.startswith("bash -s"))
    assert dl.command == (
        f"bash -s -- /tmp/yt.stub42 /tmp/yt.stub42/cookies.txt /mnt/nfs/downloads/yt-staging/yt.stub42 {URL}"
    )
    assert "yt-dlp" in dl.stdin
    nas = next(c for c in media.calls if c.host == "nas")
    assert nas.command == "bash -s -- /mnt/swift/downloads/yt-staging/yt.stub42 /mnt/tank/movies/youtube/training"
    assert not any("rm -rf" in c for c in media.commands())


def test_duplicate_with_equal_quality_is_skipped_and_path_still_emitted(
    media: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    media.on("find ", stdout=f"{FINAL}/old-[abcDEF12345].mkv\n")
    media.on("ffprobe", stdout="1080\n")
    assert download_single("training", URL) == 0
    out, err = capsys.readouterr()
    assert out == f"{FINAL}/old-[abcDEF12345].mkv\n"
    assert "Skipping download - existing file has equal or better quality" in err
    assert media.count("bash -s") == 0
    assert media.commands()[-1] == "rm -rf /tmp/yt.stub42 /mnt/nfs/downloads/yt-staging/yt.stub42 2>/dev/null || true"
    find = next(c for c in media.commands() if c.startswith("find"))
    assert find == f"find {FINAL} -type f -name '*\\[abcDEF12345\\]*' 2>/dev/null | head -1"


def test_duplicate_with_worse_quality_is_replaced(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.on("find ", stdout=f"{FINAL}/old-[abcDEF12345].mkv\n")
    media.on("ffprobe", stdout="720\n")
    assert download_single("training", URL) == 0
    assert "New quality is better - proceeding with download" in capsys.readouterr().err
    assert media.count("bash -s", host="media") == 1


def test_info_fetch_failure_warns_and_continues(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.clear()
    media.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    media.on("--print '%(id)s'", rc=1)
    media.on("bash -s", host="media", stdout="x-[unknown].mkv\n")
    assert download_single("training", URL) == 0
    err = capsys.readouterr().err
    assert "Could not fetch video info" in err
    assert "📦 Size: ~Unknown" in err


def test_download_failure_cleans_up_and_prints_troubleshooting(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.clear()
    media.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    media.on("--print '%(id)s'", stdout="abcDEF12345\nSome Video\n1080p\n0\n")
    media.on("bash -s", host="media", rc=2)
    with pytest.raises(Failure):
        download_single("training", URL)
    err = capsys.readouterr().err
    assert "Remote download failed (exit code: 2)" in err
    assert "yt --update" in err
    assert media.commands()[-1] == "rm -rf /tmp/yt.stub42 /mnt/nfs/downloads/yt-staging/yt.stub42 2>/dev/null || true"
    assert media.count("bash -s", host="nas") == 0


def test_nas_failure_keeps_staging_and_prints_recovery(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.on("bash -s", host="nas", rc=1)
    with pytest.raises(Failure):
        download_single("training", URL)
    out, err = capsys.readouterr()
    assert out == ""
    assert "NAS transfer failed" in err
    assert (
        "rsync -rl --remove-source-files /mnt/swift/downloads/yt-staging/yt.stub42/ /mnt/tank/movies/youtube/training/"
        in err
    )
    assert not any("rm -rf" in c for c in media.commands())


def test_missing_cookie_file(fake_ssh: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_YT_COOKIES", "/nope/cookies.txt")
    with pytest.raises(Failure):
        download_single("training", URL)
    assert fake_ssh.calls == []


def test_unsupported_url_warns(capsys: pytest.CaptureFixture[str]) -> None:
    warn_if_unsupported_url("https://example.com/video")
    assert "doesn't look like a supported video site" in capsys.readouterr().err
    warn_if_unsupported_url("https://www.youtube.com/watch?v=x")
    warn_if_unsupported_url("https://vimeo.com/123")
    assert capsys.readouterr().err == ""
