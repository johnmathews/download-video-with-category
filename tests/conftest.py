"""Shared fixtures: a Python fake for ssh, a cookie file, and stdin-driven prompts."""

from __future__ import annotations

import io
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
