"""Terminal I/O. Status goes to stderr; only final file paths go to stdout (pipeline-friendly)."""

from __future__ import annotations

import sys
import time

from yt.config import answers_from_stdin


class Failure(Exception):
    """Abort the current mode with an exit code; message (if any) is printed to stderr by the CLI."""

    def __init__(self, message: str | None = None, code: int = 1) -> None:
        super().__init__(message or "")
        self.message = message
        self.code = code


def info(message: str = "") -> None:
    """Progress / status line on stderr."""
    print(message, file=sys.stderr, flush=True)


def emit(path: str) -> None:
    """A final file path on stdout — the only thing that ever goes there."""
    print(path, flush=True)


def prompt(question: str) -> str | None:
    """Ask on stderr, read one line from stdin. None on EOF."""
    sys.stderr.write(question)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        return None
    return line.rstrip("\n")


def interactive() -> bool:
    """Whether prompts may be shown: a real terminal, or a test feeding answers on stdin."""
    return sys.stdin.isatty() or answers_from_stdin()


class Elapsed:
    """Wall-clock since construction, formatted like '45s' or '1m 23s'."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def __str__(self) -> str:
        secs = int(time.monotonic() - self._start)
        if secs >= 60:
            return f"{secs // 60}m {secs % 60}s"
        return f"{secs}s"


def format_size(filesize: str) -> str:
    """yt-dlp's filesize_approx (bytes as text) → 'Unknown' | '12.3 MB' | '340 MB' | '1.4 GB'."""
    if not filesize.isdigit() or filesize == "0":
        return "Unknown"
    size = int(filesize)
    size_mb = size // 1048576
    if size_mb < 1024:
        if size_mb >= 100:
            return f"{(size_mb + 5) // 10 * 10} MB"
        return f"{size / 1048576:.1f} MB"
    return f"{size / 1073741824:.1f} GB"
