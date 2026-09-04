"""Shared fixtures: a Python fake for ssh, a cookie file, stdin-driven prompts,
and a real-bash harness for the scripts in `yt/remote_scripts.py`."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from yt import ssh as ssh_module

Responder = Callable[["Call"], tuple[int, str] | None]


@dataclass
class Call:
    host: str
    command: str
    stdin: str | None
    tty: bool

    def __contains__(self, needle: str) -> bool:
        return needle in self.command


@dataclass
class FakeSSH:
    """Records every ssh call; answers by the first matching rule, else exit 0 with no output."""

    calls: list[Call] = field(default_factory=list)
    rules: list[Responder] = field(default_factory=list)

    def on(
        self, needle: str, *, rc: int = 0, stdout: str = "", host: str | None = None, stdin_has: str | None = None
    ) -> None:
        def responder(call: Call) -> tuple[int, str] | None:
            if (
                needle in call.command
                and (host is None or call.host == host)
                and (stdin_has is None or (call.stdin is not None and stdin_has in call.stdin))
            ):
                return rc, stdout
            return None

        self.rules.append(responder)

    def when(self, responder: Responder) -> None:
        self.rules.append(responder)

    def __call__(
        self, argv: list[str], *, stdin: str | None, stdin_path: Path | None, capture: bool
    ) -> subprocess.CompletedProcess[str]:
        host, command = argv[-2], argv[-1]
        if stdin is None and stdin_path is not None:
            stdin = stdin_path.read_text()
        call = Call(host, command, stdin, "-t" in argv[:-2])
        self.calls.append(call)
        for rule in self.rules:
            answer = rule(call)
            if answer is not None:
                rc, out = answer
                return subprocess.CompletedProcess(argv, rc, out if capture else "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def commands(self, host: str | None = None) -> list[str]:
        return [c.command for c in self.calls if host is None or c.host == host]

    def count(self, needle: str, host: str | None = None) -> int:
        return sum(1 for c in self.commands(host) if needle in c)


@pytest.fixture
def fake_ssh(monkeypatch: pytest.MonkeyPatch) -> FakeSSH:
    fake = FakeSSH()
    monkeypatch.setattr(ssh_module, "_execute", fake)
    return fake


@pytest.fixture
def cookies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cookies.txt"
    path.write_text("fake-cookie\n")
    monkeypatch.setenv("LOCAL_YT_COOKIES", str(path))
    return path


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Feed prompt answers through stdin (and flag that to the interactivity check)."""
    monkeypatch.setenv("YT_FITNESS_ANSWERS_FROM_STDIN", "1")

    def feed(text: str) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))

    feed("")
    return feed


@pytest.fixture
def stderr(capsys: pytest.CaptureFixture[str]) -> Iterator[Callable[[], str]]:
    yield lambda: capsys.readouterr().err


# ---------------------------------------------------------------------------
# Real-bash harness for yt/remote_scripts.py
#
# FakeSSH above proves which script was chosen and how its arguments were
# quoted. It cannot say anything about what the script *does* — the rules match
# on command text and hand back a canned tuple. The scripts are where the
# download, rename, staging and NAS transfer actually happen, so they get run
# for real: under a genuine bash, against a temp tree, with the real rsync and
# a fake yt-dlp (the only binary in them that would touch the network).
# ---------------------------------------------------------------------------


def _find_bash4() -> str | None:
    """A bash >= 4. The scripts use `${var,,}` and BASH_REMATCH; macOS ships 3.2."""
    seen: set[str] = set()
    for candidate in ("bash", "/opt/homebrew/bin/bash", "/usr/local/bin/bash", "/bin/bash"):
        path = shutil.which(candidate) if "/" not in candidate else candidate
        if not path or path in seen or not os.access(path, os.X_OK):
            continue
        seen.add(path)
        probe = subprocess.run([path, "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True, check=False)
        if probe.stdout.strip().isdigit() and int(probe.stdout.strip()) >= 4:
            return path
    return None


def _find_gnu_rsync() -> str | None:
    """GNU rsync, not macOS's openrsync — the scripts use `--info=progress2`,
    which openrsync does not implement, and the media VM / NAS run GNU rsync."""
    seen: set[str] = set()
    for candidate in ("rsync", "/opt/homebrew/bin/rsync", "/usr/local/bin/rsync", "/usr/bin/rsync"):
        path = shutil.which(candidate) if "/" not in candidate else candidate
        if not path or path in seen or not os.access(path, os.X_OK):
            continue
        seen.add(path)
        probe = subprocess.run([path, "--version"], capture_output=True, text=True, check=False)
        if probe.stdout.startswith("rsync "):
            return path
    return None


BASH4 = _find_bash4()
GNU_RSYNC = _find_gnu_rsync()

requires_remote_tools = pytest.mark.skipif(
    BASH4 is None or GNU_RSYNC is None,
    reason="the remote scripts need bash >= 4 and GNU rsync (macOS ships bash 3.2 and openrsync — `brew install bash rsync`)",
)

# Driven entirely by environment variables so the tests stay declarative.
#   FAKE_YTDLP_MODE=success|skip|fail   FAKE_YTDLP_FILES=a.mkv:b.jpg
#   FAKE_YTDLP_FAIL_FIRST=1  -> produce nothing on the first call (exercises the
#                               script's retry-without-subtitles branch)
#   FAKE_YTDLP_LOG=<path>    -> one line per invocation, holding its argv
FAKE_YTDLP_BODY = r"""
log="${FAKE_YTDLP_LOG:-/dev/null}"
calls=0
[ -f "$log" ] && calls=$(wc -l < "$log" | tr -d " ")
printf "%s\n" "$*" >> "$log"

case "${FAKE_YTDLP_MODE:-success}" in
  fail) echo "fake yt-dlp: refusing" >&2; exit 1 ;;
  skip) exit 0 ;;
esac

if [ "${FAKE_YTDLP_FAIL_FIRST:-0}" = 1 ] && [ "$calls" -eq 0 ]; then
  echo "fake yt-dlp: subtitle conversion failed" >&2
  exit 1
fi

out=""; prev=""
for arg in "$@"; do
  [ "$prev" = "-o" ] && out="$arg"
  prev="$arg"
done
dir="${out%/*}"
[ -d "$dir" ] || { echo "fake yt-dlp: no output dir in -o" >&2; exit 1; }
IFS=":" read -ra names <<< "${FAKE_YTDLP_FILES:-Uploader-Some_Video-[abcDEF12345].mkv}"
for name in "${names[@]}"; do
  [ -n "$name" ] && printf "fake video\n" > "$dir/$name"
done
exit 0
"""


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """A PATH entry holding the fake yt-dlp. rsync is deliberately the real one."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(f"#!{BASH4 or '/bin/bash'}\n{FAKE_YTDLP_BODY}")
    script.chmod(0o755)
    return bindir


@pytest.fixture
def run_remote(fake_bin: Path, tmp_path: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run a remote script the way ssh.run_script() does: `bash -s -- args...`, script on stdin."""

    def run(script: str, *args: object, **env: str) -> subprocess.CompletedProcess[str]:
        # GNU rsync ahead of macOS's openrsync, and the fake yt-dlp ahead of both.
        rsync_dir = str(Path(GNU_RSYNC).parent) if GNU_RSYNC else ""
        environ = {
            **os.environ,
            "PATH": f"{fake_bin}:{rsync_dir}:{os.environ['PATH']}",
            "FAKE_YTDLP_LOG": str(tmp_path / "ytdlp.log"),
            **env,
        }
        return subprocess.run(
            [BASH4 or "bash", "-s", "--", *(str(a) for a in args)],
            input=script,
            capture_output=True,
            text=True,
            env=environ,
            check=False,
        )

    return run


@pytest.fixture
def ytdlp_calls(tmp_path: Path) -> Callable[[], list[str]]:
    """The argv of each fake-yt-dlp invocation, in order."""
    return lambda: (tmp_path / "ytdlp.log").read_text().splitlines() if (tmp_path / "ytdlp.log").exists() else []
