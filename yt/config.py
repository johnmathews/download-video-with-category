"""Paths, hosts and environment overrides shared by every mode."""

from __future__ import annotations

import os
from pathlib import Path

MEDIA_HOST = "media"
NAS_HOST = "nas"

# Where the media VM should place final files (NFS mount already available there)
REMOTE_FINAL_BASE = "/mnt/nfs/movies/youtube"

# Two-stage SSD-staged transfer: media VM → SSD NFS → HDD (NAS-local copy)
REMOTE_STAGING_BASE = "/mnt/nfs/downloads/yt-staging"  # SSD NFS as seen from media VM
NAS_STAGING_BASE = "/mnt/swift/downloads/yt-staging"  # Same dir as seen from NAS locally
NAS_FINAL_BASE = "/mnt/tank/movies/youtube"  # HDD as seen from NAS locally

# Jellyfin "Health & Fitness" Shows library lives under this subdir of the youtube tree.
FITNESS_SUBDIR = "fitness"

COOKIE_MAX_AGE_DAYS = 7

# Shortcut flag -> (category name, description). Order is the order shown in --help.
# "g"/training was retired on 2026-09-04: `yt -f` files gym and workout videos as
# Jellyfin Health & Fitness episodes instead. cli.py still intercepts -g to say so.
CATEGORIES: dict[str, tuple[str, str]] = {
    "y": ("youtube", "General YouTube content"),
    "c": ("create", "Creative/maker content"),
    "m": ("music", "Music videos and performances"),
    "h": ("humanity", "Humanities and cultural content"),
    "t": ("travel", "Travel videos and vlogs"),
    "e": ("math+engineering", "Math and engineering content"),
}
VALID_CATEGORIES: list[str] = [name for name, _ in CATEGORIES.values()]

SUPPORTED_SITES = ("youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv")


def cookies_path() -> Path:
    """Local cookies file (Netscape cookies.txt); override with $LOCAL_YT_COOKIES."""
    override = os.environ.get("LOCAL_YT_COOKIES")
    if override:
        return Path(override)
    return Path.home() / ".config" / "yt-dlp" / "cookies" / "cookies.txt"


def ssh_binary() -> str:
    """SSH binary; $YT_SSH lets tests or wrappers substitute it."""
    return os.environ.get("YT_SSH") or "/usr/bin/ssh"


def nfo_helper_path() -> Path:
    """The stdlib-only script shipped to the media VM's python3 for fitness mode."""
    override = os.environ.get("YT_NFO_HELPER")
    if override:
        return Path(override)
    return Path(__file__).with_name("jellyfin_nfo.py")


def answers_from_stdin() -> bool:
    """Allow interactive prompts when stdin is not a tty (tests drive prompts through a pipe)."""
    return bool(os.environ.get("YT_FITNESS_ANSWERS_FROM_STDIN"))


def jellyfin_credentials() -> tuple[str, str] | None:
    url = os.environ.get("JELLYFIN_URL")
    key = os.environ.get("JELLYFIN_API_KEY")
    if url and key:
        return url.rstrip("/"), key
    return None
