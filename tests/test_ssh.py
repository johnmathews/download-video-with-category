from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt.ssh import id_glob, q, remove_remote, run_script, ssh


@patch("yt.ssh.subprocess.run")
def test_ssh_uses_batchmode_and_yt_ssh_binary(mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YT_SSH", "/opt/ssh")
    mock_run.return_value = subprocess.CompletedProcess([], 0, "out\n", "")
    result = ssh("media", "ls")
    assert mock_run.call_args[0][0] == ["/opt/ssh", "-o", "BatchMode=yes", "media", "ls"]
    assert mock_run.call_args[1]["stdin"] is subprocess.DEVNULL
    assert result.stdout == "out\n"


@patch("yt.ssh.subprocess.run")
def test_ssh_default_binary_and_tty(mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YT_SSH", raising=False)
    mock_run.return_value = subprocess.CompletedProcess([], 0, None, None)
    result = ssh("media", "sudo thing", tty=True, capture=False)
    assert mock_run.call_args[0][0][:4] == ["/usr/bin/ssh", "-o", "BatchMode=yes", "-t"]
    assert mock_run.call_args[1]["stdout"] is None
    assert result.stdout == ""


@patch("yt.ssh.subprocess.run")
def test_stdin_text_is_passed_as_input(mock_run: MagicMock) -> None:
    mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
    ssh("media", "bash -s", stdin="echo hi")
    assert mock_run.call_args[1]["input"] == "echo hi"


@patch("yt.ssh.subprocess.run")
def test_stdin_path_is_streamed_from_file(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
    cookie = tmp_path / "c.txt"
    cookie.write_text("secret")
    ssh("media", "cat > /tmp/c", stdin_path=cookie)
    handle = mock_run.call_args[1]["stdin"]
    assert handle.name == str(cookie)


def test_run_script_quotes_every_argument(fake_ssh) -> None:
    run_script("media", "echo", "/tmp/x", "Mobility & Physio", 3)
    assert fake_ssh.calls[0].command == "bash -s -- /tmp/x 'Mobility & Physio' 3"
    assert fake_ssh.calls[0].stdin == "echo"


def test_run_script_without_args(fake_ssh) -> None:
    run_script("nas", "true")
    assert fake_ssh.calls[0].command == "bash -s"


def test_remove_remote(fake_ssh) -> None:
    remove_remote("media", "/tmp/a", "/tmp/b c")
    assert fake_ssh.calls[0].command == "rm -rf /tmp/a '/tmp/b c' 2>/dev/null || true"
    remove_remote("media")
    assert len(fake_ssh.calls) == 1


def test_q() -> None:
    assert q("plain") == "plain"
    assert q("Season 03") == "'Season 03'"
    assert q(7) == "7"


class TestIdGlob:
    """`find -name` patterns built from remote-supplied video ids.

    The id comes from yt-dlp's `--print '%(id)s'` — extractor-controlled metadata
    for whatever URL was pasted, not something yt chose. It used to be spliced raw
    into a single-quoted shell literal, so an id containing a quote closed the
    literal and the rest ran as commands on the media VM.
    """

    def test_brackets_stay_literal_for_find(self) -> None:
        # Escaped, so find treats them as literal brackets rather than a character class.
        assert id_glob("abcDEF12345") == r"*\[abcDEF12345\]*"

    def test_the_quoted_form_is_unchanged_for_a_normal_id(self) -> None:
        assert q(id_glob("abcDEF12345")) == r"'*\[abcDEF12345\]*'"

    def test_a_hostile_id_cannot_break_out_of_the_command(self) -> None:
        hostile = "x'; rm -rf /mnt/tank; #"
        command = f"find /final -type f -name {q(id_glob(hostile))} 2>/dev/null | head -1"
        tokens = shlex.split(command)
        assert tokens[tokens.index("-name") + 1] == id_glob(hostile)
        assert "rm" not in tokens, f"id escaped into the command: {command}"

    def test_glob_metacharacters_in_the_id_are_escaped(self) -> None:
        assert id_glob("a*b?c") == r"*\[a\*b\?c\]*"
