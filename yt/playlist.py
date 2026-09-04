"""Playlist mode: `yt -p URL` — a whole playlist into its own Jellyfin movie-library directory."""

from __future__ import annotations

import re

from yt.config import MEDIA_HOST, NAS_FINAL_BASE, REMOTE_FINAL_BASE
from yt.cookies import check_cookies, check_ytdlp_installed
from yt.remote_scripts import PLAYLIST_ITEM_SCRIPT
from yt.session import Session
from yt.ssh import q, run_script, ssh
from yt.ui import Failure, emit, info, prompt


def slugify(text: str) -> str:
    """Lowercase ASCII words joined by single dashes; anything else becomes a dash."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _playlist_title(cookie: str, url: str) -> str:
    result = ssh(
        MEDIA_HOST,
        "yt-dlp --remote-components ejs:github --flat-playlist --playlist-items 1 --print '%(playlist_title)s' "
        f"--cookies {q(cookie)} {q(url)} 2>/dev/null",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _playlist_count(cookie: str, url: str) -> int:
    result = ssh(
        MEDIA_HOST,
        "yt-dlp --remote-components ejs:github --flat-playlist --print '%(playlist_index)s' "
        f"--cookies {q(cookie)} {q(url)} 2>/dev/null | wc -l",
    )
    text = result.stdout.strip()
    return int(text) if text.isdigit() else 0


def _confirm_slug(suggested: str) -> str | None:
    """Y/n/edit prompt. Returns the slug to use, or None to abort."""
    answer = prompt(f"Use directory '{suggested}'? [Y/n/edit]: ")
    if answer is None or answer in ("", "y", "Y"):
        return suggested
    if answer in ("n", "N"):
        info("Aborted — nothing downloaded.")
        return None
    slug = slugify(answer)
    if not slug:
        info(f"❌ '{answer}' slugifies to an empty name")
        return None
    return slug


def download_playlist(url: str) -> int:
    cookies = check_cookies()
    check_ytdlp_installed()

    # One cookie upload for the whole run; each item gets its own tmp/staging dir.
    with Session("/tmp/yt.pl.XXXXXX").open() as cookie_session:
        cookie_session.upload_cookie(cookies)
        cookie = cookie_session.cookie
        elapsed = cookie_session.elapsed

        info(f"🔍 [{elapsed}] Fetching playlist title...")
        title = _playlist_title(cookie, url)
        slug = _confirm_slug(slugify(title) or "playlist")
        if slug is None:
            cookie_session.cleanup(staging=False)
            raise Failure()

        final_remote_dir = f"{REMOTE_FINAL_BASE}/{slug}"
        nas_final_dir = f"{NAS_FINAL_BASE}/{slug}"
        archive = f"{final_remote_dir}/archive.txt"

        if ssh(MEDIA_HOST, f"mkdir -p {q(final_remote_dir)}").returncode != 0:
            info(f"❌ Could not create {final_remote_dir} on media VM")
            cookie_session.cleanup(staging=False)
            raise Failure()

        count = _playlist_count(cookie, url)
        if count == 0:
            info("❌ Playlist is empty or could not be read")
            cookie_session.cleanup(staging=False)
            raise Failure()

        info()
        info(f"📚 Playlist: {title}")
        info(f"📁 Library dir: {final_remote_dir}  ({count} items)")
        info()

        downloaded = skipped = failed = 0
        for n in range(1, count + 1):
            info(f"▶️  [{elapsed}] [{n}/{count}] processing item {n}...")
            try:
                item = Session().open()
            except Failure:
                info(f"❌ [{n}/{count}] mktemp failed")
                failed += 1
                continue

            with item:
                result = run_script(
                    MEDIA_HOST, PLAYLIST_ITEM_SCRIPT, item.tmpdir, cookie, item.staging_dir, url, n, archive
                )
                if result.returncode != 0:
                    info(f"❌ [{n}/{count}] download/staging failed")
                    item.cleanup()
                    failed += 1
                    continue
                basenames = [line for line in result.stdout.splitlines() if line]
                if not basenames:
                    info(f"⏭️  [{n}/{count}] already downloaded — skipped")
                    # The item script removes its own tmp and staging dirs on this path
                    # (see PLAYLIST_ITEM_SCRIPT) — no ssh round trip needed here.
                    skipped += 1
                    continue
                if item.nas_transfer(nas_final_dir):
                    downloaded += 1
                    for name in basenames:
                        emit(f"{final_remote_dir}/{name}")
                else:
                    info(f"❌ [{n}/{count}] NAS transfer failed — files remain on SSD: {item.nas_staging_dir}")
                    failed += 1

        cookie_session.cleanup(staging=False)
        info()
        info(f"✅ [{elapsed}] Playlist '{slug}': downloaded {downloaded}, skipped {skipped}, failed {failed}")
        return 0 if failed == 0 else 1
