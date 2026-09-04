"""Local cookie-file preflight and upload to the media VM."""

from __future__ import annotations

import time
from pathlib import Path

from yt.config import COOKIE_MAX_AGE_DAYS, MEDIA_HOST, cookies_path
from yt.ssh import q, ssh
from yt.ui import Failure, info


def check_cookies() -> Path:
    """Return the cookies file, failing if it is missing/empty and warning if it looks stale."""
    path = cookies_path()
    if not path.is_file():
        info("❌ Cookies file not found:")
        info(f"   {path}")
        info("Export youtube.com cookies to this file (Netscape cookies.txt).")
        raise Failure()
    if path.stat().st_size == 0:
        info("❌ Cookies file is empty:")
        info(f"   {path}")
        raise Failure()
    age_days = int((time.time() - path.stat().st_mtime) // 86400)
    if age_days > COOKIE_MAX_AGE_DAYS:
        info(f"⚠️  Warning: Cookies file is {age_days} days old (may be stale)")
        info("   Consider re-exporting fresh cookies from your browser")
    return path


# ssh(1) uses 255 for its own failures (host unreachable, DNS, key rejected); any other
# non-zero code came from the remote command itself.
SSH_CONNECTION_FAILED = 255


def check_ytdlp_installed() -> None:
    """The only remote preflight, so it is the first thing a user sees when the VM is down."""
    result = ssh(MEDIA_HOST, "command -v yt-dlp >/dev/null 2>&1")
    if result.returncode == SSH_CONNECTION_FAILED:
        info(f"❌ Could not reach the media VM over SSH (host '{MEDIA_HOST}')")
        info(f"   Check it is up and that `ssh {MEDIA_HOST} true` works — yt uses BatchMode,")
        info("   so a passphrase prompt or an unknown host key fails rather than asking.")
        raise Failure()
    if result.returncode != 0:
        info("❌ yt-dlp not found on media VM")
        info("   Install it with: yt --update")
        raise Failure()


def upload_cookies(local: Path, remote: str) -> bool:
    """Copy the cookie file into the remote tmp dir with restrictive permissions (umask 077)."""
    result = ssh(MEDIA_HOST, f"umask 077 && cat > {q(remote)}", stdin_path=local)
    return result.returncode == 0
