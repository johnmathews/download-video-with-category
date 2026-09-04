"""Single-video mode: `yt -y URL` — download one video into a category directory."""

from __future__ import annotations

import re

from yt.config import MEDIA_HOST, NAS_FINAL_BASE, REMOTE_FINAL_BASE, SUPPORTED_SITES, cookies_path
from yt.cookies import check_cookies, check_ytdlp_installed
from yt.remote_scripts import SINGLE_ITEM_SCRIPT
from yt.session import Session
from yt.ssh import id_glob, q, run_script, ssh
from yt.ui import Failure, emit, format_size, info

_SUPPORTED_URL_RE = re.compile(r"^https?://(www\.)?(" + "|".join(re.escape(s) for s in SUPPORTED_SITES) + ")")


def warn_if_unsupported_url(url: str) -> None:
    if not _SUPPORTED_URL_RE.match(url):
        info("⚠️  Warning: URL doesn't look like a supported video site")
        info("   Supported: YouTube, Vimeo, Dailymotion, Twitch")
        info("   Proceeding anyway...")


def fetch_video_info(cookie: str, url: str) -> tuple[str, str, str, str]:
    """(id, title, '<height>p', filesize bytes) from yt-dlp; 'unknown' placeholders on failure."""
    result = ssh(
        MEDIA_HOST,
        "yt-dlp --remote-components ejs:github --print '%(id)s' --print '%(title)s' "
        f"--print '%(height)sp' --print '%(filesize_approx)s' --cookies {q(cookie)} {q(url)} 2>/dev/null",
    )
    parts = result.stdout.splitlines()
    if result.returncode != 0 or len(parts) < 4:
        return "unknown", "Unknown Video", "0p", "0"
    return parts[0], parts[1], parts[2], parts[3]


def _height(quality: str) -> int | None:
    """Pixel height from '<n>p', or None when nobody could tell us.

    yt-dlp prints 'NA' for height on some formats and existing_quality() falls back
    to '0p' when ffprobe fails. Both used to collapse to 0, which made the
    `new <= old` comparison below always true and turned "we don't know" into
    "the file you already have is better".
    """
    digits = quality.strip().removesuffix("p")
    if not digits.isdigit() or int(digits) == 0:
        return None
    return int(digits)


def find_existing(final_dir: str, video_id: str) -> str:
    """Path of an already-downloaded file carrying [video_id] in its name, or ''."""
    result = ssh(MEDIA_HOST, f"find {q(final_dir)} -type f -name {q(id_glob(video_id))} 2>/dev/null | head -1")
    return result.stdout.strip() if result.returncode == 0 else ""


def existing_quality(path: str) -> str:
    result = ssh(
        MEDIA_HOST,
        f"ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 {q(path)} 2>/dev/null",
    )
    height = result.stdout.strip() if result.returncode == 0 else "0"
    return f"{height}p"


def download_single(category: str, url: str) -> int:
    """Download `url` into `REMOTE_FINAL_BASE/category`. Emits the final path(s) on stdout."""
    warn_if_unsupported_url(url)
    cookies = check_cookies()
    check_ytdlp_installed()

    with Session().open() as session:
        session.upload_cookie(cookies)
        remote_final_dir = f"{REMOTE_FINAL_BASE}/{category}"
        info(f"⏬ Downloading on media VM to: {session.tmpdir}")
        info(f"📦 Staging via SSD: {session.staging_dir}")
        info(f"📦 Final destination: {remote_final_dir}")
        info()

        info(f"🔍 [{session.elapsed}] Fetching video info...")
        video_id, title, new_quality, filesize = fetch_video_info(session.cookie, url)
        if video_id == "unknown":
            info("⚠️  Warning: Could not fetch video info — yt-dlp may be outdated")
            info("   Run 'yt --update' to update yt-dlp on the media VM")
            info()

        info()
        info("━" * 62)
        info(f"📹 VIDEO: {title}")
        info(f"🆔 ID: {video_id}")
        info(f"📊 Quality: {new_quality}")
        info(f"📦 Size: ~{format_size(filesize)}")
        info(f"📁 Category: {category}")
        info("━" * 62)
        info()

        info(f"🔎 [{session.elapsed}] Checking for existing downloads...")
        existing = find_existing(remote_final_dir, video_id)
        if existing:
            info(f"⚠️  Found existing file: {existing.rsplit('/', 1)[-1]}")
            old_quality = existing_quality(existing)
            info(f"   Existing quality: {old_quality}")
            info(f"   New quality: {new_quality}")
            new_height, old_height = _height(new_quality), _height(old_quality)
            if new_height is None or old_height is None:
                info()
                if new_height is None:
                    info("❌ Could not determine the new video's quality — refusing to guess")
                    info(f"   yt-dlp reported no usable height for: {url}")
                else:
                    info("❌ Could not determine the existing file's quality — refusing to guess")
                    info(f"   ffprobe could not read: {existing}")
                info("   Nothing was downloaded and nothing was changed.")
                info(f"   To download anyway, delete: {existing}")
                info("   If yt-dlp on the media VM is stale, run: yt --update")
                session.cleanup()
                raise Failure()
            if new_height <= old_height:
                info()
                info("❌ Skipping download - existing file has equal or better quality")
                info(f"   To force re-download, delete: {existing}")
                emit(existing)  # so piping (e.g. yt ... | epm) still works
                session.cleanup()
                return 0
            info()
            info("✅ New quality is better - proceeding with download")
            info("   Old file will be replaced")
        else:
            info("✓ No existing download found")
        info()

        # Stage 1: download on media VM, rsync to SSD NFS.
        result = run_script(MEDIA_HOST, SINGLE_ITEM_SCRIPT, session.tmpdir, session.cookie, session.staging_dir, url)
        if result.returncode != 0:
            info(f"❌ Remote download failed (exit code: {result.returncode})")
            info()
            info("Troubleshooting steps:")
            info("  1. Update yt-dlp:     yt --update")
            info(f"  2. Refresh cookies:   re-export cookies to {cookies_path()}")
            info("  3. Check URL:         open the URL in a browser to verify it's valid")
            session.cleanup()
            raise Failure()
        basenames = [line for line in result.stdout.splitlines() if line]
        info(f"⏱️  [{session.elapsed}] Download + SSD staging complete")

        # Stage 2: NAS-local copy from SSD (swift) to HDD (tank).
        nas_final_dir = f"{NAS_FINAL_BASE}/{category}"
        info()
        info(f"📀 [{session.elapsed}] Transferring to HDD on NAS...")
        if not session.nas_transfer(nas_final_dir):
            info("❌ NAS transfer failed")
            info()
            info("Files are safe on SSD staging. To manually complete the transfer:")
            info(f"  ssh nas 'rsync -rl --remove-source-files {q(session.nas_staging_dir)}/ {q(nas_final_dir)}/'")
            info(f"  ssh nas 'rmdir {q(session.nas_staging_dir)}'")
            raise Failure()  # staging dir deliberately kept for manual recovery

        info()
        info(f"✅ [{session.elapsed}] Successfully downloaded to: {remote_final_dir}")
        for name in basenames:
            emit(f"{remote_final_dir}/{name}")
        return 0
