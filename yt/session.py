"""A download session on the media VM: tmp dir, matching SSD staging dir, uploaded cookie.

Replaces the zsh INT/TERM traps: leaving the `with` block via KeyboardInterrupt removes the
remote tmp and staging dirs and exits 130. Normal-path cleanup is explicit (the remote scripts
remove the tmp dir; the NAS script removes the staging dir), and failure paths decide per case
whether staged files are kept for manual recovery.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self

from yt.config import MEDIA_HOST, NAS_HOST, NAS_STAGING_BASE, REMOTE_STAGING_BASE
from yt.cookies import upload_cookies
from yt.remote_scripts import NAS_SCRIPT
from yt.ssh import remove_remote, run_script, ssh
from yt.ui import Elapsed, Failure, info


class Session:
    def __init__(self, template: str = "/tmp/yt.XXXXXX") -> None:
        self._template = template
        self.elapsed = Elapsed()
        self.tmpdir = ""
        self.cookie = ""
        self.staging_subdir = ""
        self.staging_dir = ""  # SSD staging as seen from the media VM
        self.nas_staging_dir = ""  # the same dir as seen from the NAS

    def open(self) -> Self:
        """mktemp on the media VM and derive the staging dirs from its basename."""
        result = ssh(MEDIA_HOST, f"mktemp -d {self._template}")
        if result.returncode != 0 or not result.stdout.strip():
            info("❌ Failed to create remote temp dir")
            raise Failure()
        self.tmpdir = result.stdout.strip()
        self.cookie = f"{self.tmpdir}/cookies.txt"
        self.staging_subdir = PurePosixPath(self.tmpdir).name
        self.staging_dir = f"{REMOTE_STAGING_BASE}/{self.staging_subdir}"
        self.nas_staging_dir = f"{NAS_STAGING_BASE}/{self.staging_subdir}"
        return self

    def upload_cookie(self, local: Path) -> None:
        info(f"🍪 [{self.elapsed}] Copying cookies to media VM...")
        if not upload_cookies(local, self.cookie):
            info("❌ Failed to copy cookies to media VM")
            self.cleanup(staging=False)
            raise Failure()

    def cleanup(self, *, staging: bool = True) -> None:
        paths = [self.tmpdir] if self.tmpdir else []
        if staging and self.staging_dir:
            paths.append(self.staging_dir)
        remove_remote(MEDIA_HOST, *paths)

    def nas_transfer(self, nas_final_dir: str) -> bool:
        """Stage 2: NAS-local copy from SSD staging into the final HDD dir."""
        return run_script(NAS_HOST, NAS_SCRIPT, self.nas_staging_dir, nas_final_dir).returncode == 0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if isinstance(exc, KeyboardInterrupt):
            self.cleanup()
            raise SystemExit(130) from None
