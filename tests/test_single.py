"""Single-video mode against the fake ssh. Mirrors what the zsh path did call-for-call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from yt.single import download_single, warn_if_unsupported_url
from yt.ssh import q
from yt.ui import Failure

URL = "https://youtu.be/abcDEF12345"
FINAL = "/mnt/nfs/movies/youtube/music"


@pytest.fixture
def media(fake_ssh: Any, cookies: Path) -> Any:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    fake_ssh.on("--print '%(id)s'", stdout="abcDEF12345\nSome Video\n1080p\n2200000000\n")
    fake_ssh.on("bash -s", host="media", stdout="Uploader-Some_Video-[abcDEF12345].mkv\n")
    return fake_ssh


def test_happy_path(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert download_single("music", URL) == 0
    out, err = capsys.readouterr()
    assert out == f"{FINAL}/Uploader-Some_Video-[abcDEF12345].mkv\n"
    assert "📹 VIDEO: Some Video" in err
    assert "📦 Size: ~2.0 GB" in err
    assert "✓ No existing download found" in err
    assert "Successfully downloaded to: /mnt/nfs/movies/youtube/music" in err
    # cookie went up under umask 077, download script got quoted args, NAS stage-2 targeted the category dir
    assert media.count("umask 077 && cat > /tmp/yt.stub42/cookies.txt") == 1
    dl = next(c for c in media.calls if c.host == "media" and c.command.startswith("bash -s"))
    assert dl.command == (
        f"bash -s -- /tmp/yt.stub42 /tmp/yt.stub42/cookies.txt /mnt/nfs/downloads/yt-staging/yt.stub42 {URL}"
    )
    assert "yt-dlp" in dl.stdin
    nas = next(c for c in media.calls if c.host == "nas")
    assert nas.command == "bash -s -- /mnt/swift/downloads/yt-staging/yt.stub42 /mnt/tank/movies/youtube/music"
    assert not any("rm -rf" in c for c in media.commands())


def test_duplicate_with_equal_quality_is_skipped_and_path_still_emitted(
    media: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    media.on("find ", stdout=f"{FINAL}/old-[abcDEF12345].mkv\n")
    media.on("ffprobe", stdout="1080\n")
    assert download_single("music", URL) == 0
    out, err = capsys.readouterr()
    assert out == f"{FINAL}/old-[abcDEF12345].mkv\n"
    assert "Skipping download - existing file has equal or better quality" in err
    assert media.count("bash -s") == 0
    assert media.commands()[-1] == "rm -rf /tmp/yt.stub42 /mnt/nfs/downloads/yt-staging/yt.stub42 2>/dev/null || true"
    find = next(c for c in media.commands() if c.startswith("find"))
    assert find == f"find {FINAL} -type f -name '*\\[abcDEF12345\\]*' 2>/dev/null | head -1"


def test_unknown_new_quality_refuses_to_claim_the_existing_file_is_better(
    fake_ssh: Any, cookies: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """yt-dlp prints 'NA' for height on some formats, giving new_quality='NAp'.

    _height() mapped that to 0, and `0 <= anything` made the skip branch always win —
    so yt reported "existing file has equal or better quality", emitted the old path
    and exited 0, having compared against a height it never learned.
    """
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    fake_ssh.on("--print '%(id)s'", stdout="abcDEF12345\nSome Video\nNAp\n2200000000\n")
    fake_ssh.on("find ", stdout=f"{FINAL}/old-[abcDEF12345].mkv\n")
    fake_ssh.on("ffprobe", stdout="1080\n")
    fake_ssh.on("bash -s", host="media", stdout="Uploader-Some_Video-[abcDEF12345].mkv\n")

    with pytest.raises(Failure):
        download_single("music", URL)

    out, err = capsys.readouterr()
    assert out == "", "must not emit a path it cannot vouch for"
    assert "Could not determine the new video's quality" in err
    assert "Skipping download - existing file has equal or better quality" not in err


def test_unknown_existing_quality_also_refuses_to_guess(
    fake_ssh: Any, cookies: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The mirror case: ffprobe failed, so existing_quality() is '0p'."""
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    fake_ssh.on("--print '%(id)s'", stdout="abcDEF12345\nSome Video\n1080p\n2200000000\n")
    fake_ssh.on("find ", stdout=f"{FINAL}/old-[abcDEF12345].mkv\n")
    fake_ssh.on("ffprobe", rc=1)
    fake_ssh.on("bash -s", host="media", stdout="x.mkv\n")

    with pytest.raises(Failure):
        download_single("music", URL)

    assert "Could not determine the existing file's quality" in capsys.readouterr().err


def test_failed_info_fetch_still_downloads_when_nothing_matches(
    fake_ssh: Any, cookies: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression guard on the fix's blast radius.

    When the whole --print call fails, video_id is 'unknown', so the find matches
    nothing and there is no comparison to refuse — the download must still proceed.
    """
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    fake_ssh.on("--print '%(id)s'", rc=1)
    fake_ssh.on("find ", stdout="")
    fake_ssh.on("bash -s", host="media", stdout="Uploader-Some_Video-[abcDEF12345].mkv\n")

    assert download_single("music", URL) == 0
    assert fake_ssh.count("bash -s", host="media") == 1
    assert "Could not fetch video info" in capsys.readouterr().err


def test_duplicate_with_worse_quality_is_replaced(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.on("find ", stdout=f"{FINAL}/old-[abcDEF12345].mkv\n")
    media.on("ffprobe", stdout="720\n")
    assert download_single("music", URL) == 0
    assert "New quality is better - proceeding with download" in capsys.readouterr().err
    assert media.count("bash -s", host="media") == 1


def test_info_fetch_failure_warns_and_continues(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.clear()
    media.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    media.on("--print '%(id)s'", rc=1)
    media.on("bash -s", host="media", stdout="x-[unknown].mkv\n")
    assert download_single("music", URL) == 0
    err = capsys.readouterr().err
    assert "Could not fetch video info" in err
    assert "📦 Size: ~Unknown" in err


def test_download_failure_cleans_up_and_prints_troubleshooting(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.rules.clear()
    media.on("mktemp -d", stdout="/tmp/yt.stub42\n")
    media.on("--print '%(id)s'", stdout="abcDEF12345\nSome Video\n1080p\n0\n")
    media.on("bash -s", host="media", rc=2)
    with pytest.raises(Failure):
        download_single("music", URL)
    err = capsys.readouterr().err
    assert "Remote download failed (exit code: 2)" in err
    assert "yt --update" in err
    assert media.commands()[-1] == "rm -rf /tmp/yt.stub42 /mnt/nfs/downloads/yt-staging/yt.stub42 2>/dev/null || true"
    assert media.count("bash -s", host="nas") == 0


def test_nas_failure_keeps_staging_and_prints_recovery(media: Any, capsys: pytest.CaptureFixture[str]) -> None:
    media.on("bash -s", host="nas", rc=1)
    with pytest.raises(Failure):
        download_single("music", URL)
    out, err = capsys.readouterr()
    assert out == ""
    assert "NAS transfer failed" in err
    assert (
        "rsync -rl --remove-source-files /mnt/swift/downloads/yt-staging/yt.stub42/ /mnt/tank/movies/youtube/music/"
        in err
    )
    assert not any("rm -rf" in c for c in media.commands())


def test_missing_cookie_file(fake_ssh: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_YT_COOKIES", "/nope/cookies.txt")
    with pytest.raises(Failure):
        download_single("music", URL)
    assert fake_ssh.calls == []


def test_unsupported_url_warns(capsys: pytest.CaptureFixture[str]) -> None:
    warn_if_unsupported_url("https://example.com/video")
    assert "doesn't look like a supported video site" in capsys.readouterr().err
    warn_if_unsupported_url("https://www.youtube.com/watch?v=x")
    warn_if_unsupported_url("https://vimeo.com/123")
    assert capsys.readouterr().err == ""


class TestSupersededFileRemoval:
    """`yt` printed "Old file will be replaced" and then never replaced anything.

    yt-dlp builds the filename from the *current* uploader and title, and YouTube titles
    change — so a quality upgrade usually lands under a new name, rsync writes it
    alongside the old one, and the category dir ends up with two files carrying the same
    [id]. The next run's find_existing() may then match either.
    """

    OLD = f"{FINAL}/Old_Uploader-Old_Title-[abcDEF12345].mkv"
    NEW = f"{FINAL}/Uploader-Some_Video-[abcDEF12345].mkv"

    def _upgrade(self, media: Any, existing: str) -> None:
        media.on("find ", stdout=f"{existing}\n")
        media.on("ffprobe", stdout="720\n")  # existing 720p vs new 1080p -> upgrade

    def test_removes_the_old_file_once_the_new_one_has_landed(
        self, media: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._upgrade(media, self.OLD)
        assert download_single("music", URL) == 0
        assert f"rm -f {q(self.OLD)}" in " ".join(media.commands())  # q(): the path has [brackets]
        assert "Removed superseded file" in capsys.readouterr().err

    def test_does_not_delete_when_rsync_already_overwrote_it(
        self, media: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Same filename means the transfer replaced it in place; deleting would remove
        the file we just downloaded."""
        self._upgrade(media, self.NEW)
        assert download_single("music", URL) == 0
        assert "rm -f" not in " ".join(media.commands())
        assert "Removed superseded file" not in capsys.readouterr().err

    def test_does_not_delete_when_the_nas_transfer_failed(self, media: Any) -> None:
        """The new file never reached the library, so the old one is all there is."""
        self._upgrade(media, self.OLD)
        media.rules.insert(0, lambda c: (1, "") if c.host == "nas" else None)
        with pytest.raises(Failure):
            download_single("music", URL)
        assert "rm -f" not in " ".join(media.commands()), "deleted the old file after a failed transfer"

    def test_does_not_delete_when_there_was_no_existing_file(self, media: Any) -> None:
        media.on("find ", stdout="")
        assert download_single("music", URL) == 0
        assert "rm -f" not in " ".join(media.commands())

    def test_does_not_delete_when_the_download_was_skipped(self, media: Any) -> None:
        media.on("find ", stdout=f"{self.OLD}\n")
        media.on("ffprobe", stdout="1080\n")  # equal quality -> skip, keep the old file
        assert download_single("music", URL) == 0
        assert "rm -f" not in " ".join(media.commands())

    def test_a_failed_removal_warns_rather_than_aborting(self, media: Any, capsys: pytest.CaptureFixture[str]) -> None:
        self._upgrade(media, self.OLD)
        media.rules.insert(0, lambda c: (1, "") if c.command.startswith("rm -f ") else None)
        assert download_single("music", URL) == 0, "the download itself succeeded"
        err = capsys.readouterr().err
        assert "Could not remove" in err
        assert self.OLD in err
