"""The destination preflight: both views of the final directory are checked before any download.

Regression for 2026-11-19: the NAS crashed and rebooted with its encrypted datasets locked.
yt fetched info, reported "No existing download found" for a directory it could not read,
downloaded 600 MB, and only failed at the stage-2 `mkdir` on the NAS.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from yt.config import NAS_FINAL_BASE, REMOTE_FINAL_BASE
from yt.destination import CHECK_TIMEOUT_SECONDS, check_command, check_destinations
from yt.fitness import add_to_show
from yt.playlist import download_playlist
from yt.single import download_single, find_existing
from yt.ui import Failure

URL = "https://youtu.be/abcDEF12345"
CHECK = "timeout -s KILL"
STALE = f"ls: cannot access '{REMOTE_FINAL_BASE}': Stale file handle"


class TestCheckDestinations:
    def test_checks_the_media_vm_view_then_the_nas_view(self, fake_ssh: Any) -> None:
        check_destinations()
        assert [(c.host, c.command) for c in fake_ssh.calls] == [
            ("media", check_command(REMOTE_FINAL_BASE)),
            ("nas", check_command(NAS_FINAL_BASE)),
        ]

    def test_stale_media_mount_fails_with_the_kernels_reason(self, fake_ssh: Any, stderr: Any) -> None:
        fake_ssh.on(CHECK, host="media", rc=3, stdout=f"{STALE}\n")
        with pytest.raises(Failure):
            check_destinations()
        err = stderr()
        assert f"❌ Download destination on the media VM is not usable: {REMOTE_FINAL_BASE}" in err
        assert STALE in err
        assert "unlock its encrypted datasets" in err
        assert "Nothing was downloaded." in err
        assert fake_ssh.count(CHECK, host="nas") == 0, "stops at the first unusable view"

    def test_locked_nas_dataset_fails(self, fake_ssh: Any, stderr: Any) -> None:
        missing = f"ls: cannot access '{NAS_FINAL_BASE}': No such file or directory"
        fake_ssh.on(CHECK, host="nas", rc=3, stdout=f"{missing}\n")
        with pytest.raises(Failure):
            check_destinations()
        err = stderr()
        assert f"❌ Download destination on the NAS is not usable: {NAS_FINAL_BASE}" in err
        assert missing in err

    def test_not_writable(self, fake_ssh: Any, stderr: Any) -> None:
        fake_ssh.on(CHECK, host="nas", rc=4, stdout=f"not writable by truenas_admin: {NAS_FINAL_BASE}\n")
        with pytest.raises(Failure):
            check_destinations()
        assert f"not writable by truenas_admin: {NAS_FINAL_BASE}" in stderr()

    def test_hung_nfs_mount_times_out(self, fake_ssh: Any, stderr: Any) -> None:
        fake_ssh.on(CHECK, host="media", rc=137)
        with pytest.raises(Failure):
            check_destinations()
        assert f"no response within {CHECK_TIMEOUT_SECONDS}s" in stderr()

    def test_unreachable_nas(self, fake_ssh: Any, stderr: Any) -> None:
        fake_ssh.on(CHECK, host="nas", rc=255)
        with pytest.raises(Failure):
            check_destinations()
        err = stderr()
        assert "❌ Could not reach the NAS over SSH (host 'nas')" in err
        assert "Nothing was downloaded." in err

    def test_unexpected_exit_without_output_still_says_something(self, fake_ssh: Any, stderr: Any) -> None:
        fake_ssh.on(CHECK, host="media", rc=127)
        with pytest.raises(Failure):
            check_destinations()
        assert "check failed (exit code 127)" in stderr()


def _run_check(path: Path | str) -> subprocess.CompletedProcess[str]:
    """The exact command string yt sends, run by a local /bin/sh the way sshd would."""
    return subprocess.run(["/bin/sh", "-c", check_command(str(path))], capture_output=True, text=True, check=False)


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "command -v timeout"], capture_output=True, check=False).returncode != 0,
    reason="needs coreutils `timeout` (brew install coreutils)",
)
class TestCheckCommandForReal:
    def test_usable_directory_passes_silently(self, tmp_path: Path) -> None:
        result = _run_check(tmp_path)
        assert (result.returncode, result.stdout) == (0, "")

    def test_missing_directory(self, tmp_path: Path) -> None:
        result = _run_check(tmp_path / "locked")
        assert result.returncode == 3
        assert "No such file or directory" in result.stdout
        assert len(result.stdout.splitlines()) == 1

    def test_a_file_is_not_a_directory(self, tmp_path: Path) -> None:
        (tmp_path / "f").write_text("x")
        result = _run_check(tmp_path / "f")
        assert (result.returncode, result.stdout.strip()) == (3, f"not a directory: {tmp_path / 'f'}")

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
    def test_read_only_directory(self, tmp_path: Path) -> None:
        ro = tmp_path / "ro"
        ro.mkdir()
        ro.chmod(0o555)
        try:
            result = _run_check(ro)
        finally:
            ro.chmod(0o755)
        assert result.returncode == 4
        assert result.stdout.startswith("not writable by ")

    def test_hostile_path_is_one_argument(self, tmp_path: Path) -> None:
        odd = tmp_path / "it's $(touch pwned) dir"
        odd.mkdir()
        assert _run_check(odd).returncode == 0
        assert not (tmp_path / "pwned").exists()


class TestEveryModeChecksBeforeDownloading:
    """A failed preflight leaves nothing behind: no tmp dir, no cookie upload, no download."""

    @pytest.fixture
    def stale(self, fake_ssh: Any, cookies: Path) -> Any:
        fake_ssh.on(CHECK, host="media", rc=3, stdout=f"{STALE}\n")
        return fake_ssh

    def _assert_nothing_started(self, fake_ssh: Any, err: str) -> None:
        assert "Download destination on the media VM is not usable" in err, "failed for the right reason"
        assert fake_ssh.count("mktemp") == 0
        assert fake_ssh.count("umask 077") == 0
        assert fake_ssh.count("bash -s") == 0

    def test_single(self, stale: Any, stderr: Any) -> None:
        with pytest.raises(Failure):
            download_single("humanity", URL)
        self._assert_nothing_started(stale, stderr())

    def test_playlist(self, stale: Any, stderr: Any) -> None:
        with pytest.raises(Failure):
            download_playlist("https://www.youtube.com/playlist?list=PLtest")
        self._assert_nothing_started(stale, stderr())

    def test_fitness(self, stale: Any, stderr: Any) -> None:
        with pytest.raises(Failure):
            add_to_show("Kettlebell/2", URL)
        self._assert_nothing_started(stale, stderr())


class TestFindExisting:
    FINAL = f"{REMOTE_FINAL_BASE}/humanity"

    def test_failed_search_is_not_reported_as_no_existing_download(
        self, fake_ssh: Any, cookies: Path, stderr: Any
    ) -> None:
        fake_ssh.on("mktemp -d", stdout="/tmp/yt.stub42\n")
        fake_ssh.on("--print '%(id)s'", stdout="abcDEF12345\nSome Video\n1080p\n2200000000\n")
        fake_ssh.on(" find ", rc=1)
        with pytest.raises(Failure):
            download_single("humanity", URL)
        err = stderr()
        assert f"❌ Could not search {self.FINAL} for an existing download" in err
        assert "No existing download found" not in err
        assert fake_ssh.count("bash -s") == 0, "nothing downloaded"
        assert fake_ssh.commands()[-1].startswith("rm -rf /tmp/yt.stub42 "), "session cleaned up"

    def test_a_match_counts_even_if_find_also_hit_an_error(self, fake_ssh: Any) -> None:
        fake_ssh.on(" find ", rc=1, stdout=f"{self.FINAL}/old-[abcDEF12345].mkv\n")
        assert find_existing(self.FINAL, "abcDEF12345") == f"{self.FINAL}/old-[abcDEF12345].mkv"

    def test_command_for_real(self, fake_ssh: Any, tmp_path: Path) -> None:
        """Run the generated command under a real sh: a not-yet-created category is "none", a match is found."""
        find_existing(str(tmp_path / "new-category"), "abcDEF12345")
        missing = subprocess.run(
            ["/bin/sh", "-c", fake_ssh.calls[-1].command], capture_output=True, text=True, check=False
        )
        assert (missing.returncode, missing.stdout) == (0, "")

        (tmp_path / "Up-Some-[abcDEF12345].mkv").write_text("x")
        (tmp_path / "Up-Other-[zzz].mkv").write_text("x")
        find_existing(str(tmp_path), "abcDEF12345")
        found = subprocess.run(
            ["/bin/sh", "-c", fake_ssh.calls[-1].command], capture_output=True, text=True, check=False
        )
        assert (found.returncode, found.stdout.strip()) == (0, str(tmp_path / "Up-Some-[abcDEF12345].mkv"))
