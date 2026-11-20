"""Preflight: both ends of the final transfer are usable before anything is downloaded.

A download writes to two views of the same HDD directory: the media VM reads it over NFS
(`REMOTE_FINAL_BASE`, for the existing-file check and the playlist archive) and the NAS writes
it locally in stage 2 (`NAS_FINAL_BASE`). When the NAS restarts, its encrypted datasets stay
locked until someone unlocks them, so the NAS-side directory vanishes and the media VM's NFS
mount goes stale. Without this check yt found out only after a full download, at the stage-2
`mkdir`, and the existing-file search reported "no existing download" for a directory it could
not read.
"""

from __future__ import annotations

from yt.config import MEDIA_HOST, NAS_FINAL_BASE, NAS_HOST, REMOTE_FINAL_BASE
from yt.cookies import SSH_CONNECTION_FAILED
from yt.ssh import q, ssh
from yt.ui import Failure, info

# A hard NFS mount whose server is down blocks reads indefinitely. SIGKILL is the one signal
# that interrupts an NFS wait, so `timeout` sends it rather than the default SIGTERM.
CHECK_TIMEOUT_SECONDS = 15
TIMED_OUT = 128 + 9  # `timeout -s KILL` exits with the killed child's status

# Runs under the remote /bin/sh (dash on the NAS). $1 is the directory. stdout carries one
# line naming the problem; exit 3 = missing or unreadable, 4 = not writable.
# `ls` rather than `test -d` alone: it reads the directory, so a stale NFS handle fails here
# with the kernel's own wording ("Stale file handle") instead of a bare false.
_CHECK = (
    'd="$1"; '
    'if ! err=$(ls -A -- "$d" 2>&1 >/dev/null); then printf "%s\\n" "${err:-cannot read $d}" | head -n 1; exit 3; fi; '
    '[ -d "$d" ] || { echo "not a directory: $d"; exit 3; }; '
    '[ -w "$d" ] || { echo "not writable by $(id -un): $d"; exit 4; }'
)


def check_command(path: str) -> str:
    return f"timeout -s KILL {CHECK_TIMEOUT_SECONDS} sh -c {q(_CHECK)} _ {q(path)}"


def check_destinations() -> None:
    """Fail before downloading if either view of the final directory is unusable."""
    for host, label, path in ((MEDIA_HOST, "media VM", REMOTE_FINAL_BASE), (NAS_HOST, "NAS", NAS_FINAL_BASE)):
        result = ssh(host, check_command(path))
        if result.returncode == 0:
            continue
        if result.returncode == SSH_CONNECTION_FAILED:
            info(f"❌ Could not reach the {label} over SSH (host '{host}')")
            info(f"   Check it is up and that `ssh {host} true` works.")
        else:
            if result.returncode == TIMED_OUT:
                reason = f"no response within {CHECK_TIMEOUT_SECONDS}s — is the NAS up?"
            else:
                reason = result.stdout.strip() or f"check failed (exit code {result.returncode})"
            info(f"❌ Download destination on the {label} is not usable: {path}")
            info(f"   {reason}")
            info("   If the NAS restarted: unlock its encrypted datasets in TrueNAS, then clear")
            info("   stale NFS mounts on the media VM (sudo umount -l /mnt/nfs/<share>).")
        info("   Nothing was downloaded.")
        raise Failure()
