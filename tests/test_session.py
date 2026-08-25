from __future__ import annotations

from pathlib import Path

import pytest

from yt.session import Session
from yt.ui import Failure


def test_open_derives_staging_dirs(fake_ssh) -> None:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.a1b2c3\n")
    s = Session().open()
    assert s.tmpdir == "/tmp/yt.a1b2c3"
    assert s.cookie == "/tmp/yt.a1b2c3/cookies.txt"
    assert s.staging_dir == "/mnt/nfs/downloads/yt-staging/yt.a1b2c3"
    assert s.nas_staging_dir == "/mnt/swift/downloads/yt-staging/yt.a1b2c3"
    assert fake_ssh.calls[0].command == "mktemp -d /tmp/yt.XXXXXX"


def test_open_failure(fake_ssh, capsys: pytest.CaptureFixture[str]) -> None:
    fake_ssh.on("mktemp -d", rc=1)
    with pytest.raises(Failure):
        Session().open()
    assert "Failed to create remote temp dir" in capsys.readouterr().err


def test_cookie_upload_failure_cleans_tmpdir_only(fake_ssh, cookies: Path) -> None:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.x\n")
    fake_ssh.on("umask 077", rc=1)
    s = Session().open()
    with pytest.raises(Failure):
        s.upload_cookie(cookies)
    assert fake_ssh.commands()[-1] == "rm -rf /tmp/yt.x 2>/dev/null || true"


def test_keyboard_interrupt_cleans_both_and_exits_130(fake_ssh) -> None:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.x\n")
    with pytest.raises(SystemExit) as exc, Session().open():
        raise KeyboardInterrupt
    assert exc.value.code == 130
    assert fake_ssh.commands()[-1] == "rm -rf /tmp/yt.x /mnt/nfs/downloads/yt-staging/yt.x 2>/dev/null || true"


def test_other_exceptions_propagate_without_cleanup(fake_ssh) -> None:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.x\n")
    with pytest.raises(ValueError), Session().open():
        raise ValueError("x")
    assert not any("rm -rf" in c for c in fake_ssh.commands())


def test_nas_transfer_runs_shared_script(fake_ssh) -> None:
    fake_ssh.on("mktemp -d", stdout="/tmp/yt.x\n")
    s = Session().open()
    assert s.nas_transfer("/mnt/tank/movies/youtube/training")
    call = fake_ssh.calls[-1]
    assert call.host == "nas"
    assert call.command == "bash -s -- /mnt/swift/downloads/yt-staging/yt.x /mnt/tank/movies/youtube/training"
    assert call.stdin is not None
    assert "rsync -rl --info=progress2 --remove-source-files" in call.stdin
