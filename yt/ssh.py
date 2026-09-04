"""The single choke point for every remote call (media VM and NAS)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from yt.config import ssh_binary


def q(value: str | int) -> str:
    """Shell-quote a value for embedding in a remote command line."""
    return shlex.quote(str(value))


def _execute(
    argv: list[str],
    *,
    stdin: str | None,
    stdin_path: Path | None,
    capture: bool,
) -> subprocess.CompletedProcess[str]:
    """Run ssh. Tests replace this function; nothing else in the package touches subprocess."""
    stdout = subprocess.PIPE if capture else None
    if stdin_path is not None:
        with stdin_path.open("rb") as handle:
            return subprocess.run(argv, stdin=handle, stdout=stdout, text=True, check=False)
    if stdin is not None:
        return subprocess.run(argv, input=stdin, stdout=stdout, text=True, check=False)
    return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stdout, text=True, check=False)


# Connection options, in one place so every call gets them.
#   BatchMode           never prompt — a passphrase or unknown host key fails instead of hanging.
#   ConnectTimeout      an unreachable VM fails in 10s rather than the kernel's TCP timeout.
#   ServerAlive*        30s x 6 = 3 minutes of silence before giving up on a frozen VM. Generous
#                       on purpose: a NAS busy with a large rsync can be quiet for a while, and
#                       dropping a good transfer is worse than waiting.
SSH_OPTIONS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ServerAliveInterval=30",
    "-o",
    "ServerAliveCountMax=6",
]


def ssh(
    host: str,
    command: str,
    *,
    stdin: str | None = None,
    stdin_path: Path | None = None,
    capture: bool = True,
    tty: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run `command` on `host` with BatchMode. stderr is inherited so remote progress reaches the terminal."""
    argv = [ssh_binary(), *SSH_OPTIONS]
    if tty:
        argv.append("-t")
    argv += [host, command]
    result = _execute(argv, stdin=stdin, stdin_path=stdin_path, capture=capture)
    if result.stdout is None:
        result.stdout = ""
    return result


def run_script(host: str, script: str, *args: str | int, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Pipe a bash script to `bash -s -- args...` on the host. Args are quoted, never interpolated."""
    command = "bash -s -- " + " ".join(q(a) for a in args) if args else "bash -s"
    return ssh(host, command, stdin=script, capture=capture)


def id_glob(video_id: str) -> str:
    """A `find -name` pattern matching "[<video_id>]" anywhere in a basename.

    Two levels of escaping, both needed. The brackets around the id are escaped so
    find reads them as literal brackets rather than a character class, and any glob
    metacharacter *inside* the id is escaped so a strange id cannot widen the match.
    The caller still passes the result through `q()` — this handles find's globbing,
    `q` handles the shell.

    The id is extractor-controlled metadata (yt-dlp's `--print '%(id)s'`), not a
    value yt chose, so it is untrusted input like any other.
    """
    escaped = "".join("\\" + ch if ch in "\\[]*?" else ch for ch in video_id)
    return f"*\\[{escaped}\\]*"


def remove_remote(host: str, *paths: str) -> None:
    """Best-effort `rm -rf` of remote paths (cleanup; failures are ignored)."""
    if not paths:
        return
    ssh(host, f"rm -rf {' '.join(q(p) for p in paths)} 2>/dev/null || true")


def lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    """stdout split into lines, trailing newline dropped."""
    return result.stdout.splitlines()
