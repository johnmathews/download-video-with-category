#!/usr/bin/env python3
"""Write a Jellyfin episode .nfo (and name the thumbnail) for a freshly downloaded video.

Used by `yt -f` (fitness mode). Runs ON THE MEDIA VM, fed over ssh stdin:

    ssh media python3 - <staging_dir> <show> <season> <episode> < jellyfin_nfo.py

For every video file in <staging_dir> it expects yt-dlp's sidecars written by
`--write-info-json` (and optionally `--write-thumbnail`) with the same stem,
and writes:

    <stem>.nfo         title / showtitle / season / episode / plot / aired / year /
                       studio / sorttitle / uniqueid(YoutubeMetadata)
    <stem>-thumb.jpg   the thumbnail, renamed from <stem>.jpg (if present)

and deletes the .info.json (Jellyfin does not need it; the YouTube Metadata plugin
is disabled for the Health & Fitness library). Prints the nfo paths it wrote.

The description cleaning is a copy of `clean_overview()` from
proxmox-setup/scripts/jellyfin-fitness-migration/migrate.py — keep the two in step.
Only the standard library is used (the media VM has python3, nothing else).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

MEDIA_EXTS = {".mkv", ".mp4", ".webm", ".m4v", ".mov"}

# --- description cleaning (mirror of migrate.py clean_overview) ------------------
_URL_RE = re.compile(r"(https?://|www\.|\b[a-z0-9.-]+\.(com|net|org|io|ly|gg|tv|co|online|me|uk|app)\b(/|\b))", re.I)
_BOILER_RE = re.compile(
    r"^(follow( me| us| along)?\b|subscribe|join (us|our|the crew|here|now|my (discord|patreon|channel|community|newsletter))\b|shop\b|support (this|us|the|me|our)\b|patreon|merch|"
    r"music (i use|by|score)|faq|instagram|twitter|facebook|tiktok|discord|sponsor|use code|check out|sign ?up|tag us|"
    r"get the bonus|thanks?( you)? for (watching|reading|listening)|my favou?rite gear|gear i use|what (workout )?gear|"
    r"what'?s your camera|podcast credit|produced|directed|director of|edited by|filmed by|shot by|source:|"
    r"full .{0,30}protocol|home gym|timestamps?|chapters?|have any questions|questions\?|leave a comment|comment below|"
    r"let me know|like and|hit the|turn on notifications|#|\W*$)", re.I)
_LABEL_RE = re.compile(r"^.{1,60}[:：]\s*$")
_PROMO_RE = re.compile(r"(discount|coupon|promo|\bcode\b|% ?off|offer|seminar|click|link below|sign ?up|training today|teacher training|"
                       r"for purchase|limited time|free trial|download the app|available now)", re.I)
_SENTENCE_RE = re.compile(r"[.!?…]")
_TIMESTAMP_RE = re.compile(r"^\(?\d{1,2}:\d{2}")
_BULLET_RE = re.compile(r"^[\s•►▶\-—–*·>]+")


def _prose_lines(paragraph: str) -> list[str]:
    keep: list[str] = []
    lines = [ln.strip() for ln in paragraph.splitlines() if ln.strip()]
    if lines and sum(1 for ln in lines if _BULLET_RE.match(ln) and _BULLET_RE.match(ln).end() > 0) > len(lines) / 2:  # type: ignore[union-attr]
        return []
    for ln in lines:
        core = _BULLET_RE.sub("", ln)
        if _URL_RE.search(core):
            core = re.sub(r"(\(?(https?://|www\.)\S+\)?|\b\S+\.(com|net|org|io|gg|tv|ly|me|app|online|uk|us)\S*)", "", core, flags=re.I)
            core = re.sub(r"[\s➡️→>:\-–—|]+$", "", core).strip()
            if len(core) < 40 or not _SENTENCE_RE.search(core):
                continue
        if _TIMESTAMP_RE.match(core) or _BOILER_RE.match(core) or _LABEL_RE.match(core) or _PROMO_RE.search(core):
            continue
        core = re.sub(r"\s*#\w+", "", core)
        core = re.sub(r"[⁦-⁩​-‏]", "", core).strip()
        if len(core) >= 3:
            keep.append(core)
    text = " ".join(keep)
    if keep:
        words = text.split()
        caps = sum(1 for w in words if w.isupper() or w[:1].isupper()) / max(1, len(words))
        if not _SENTENCE_RE.search(text) and (len(text) < 80 or caps > 0.5):
            return []
        if len(words) >= 3 and sum(1 for w in words if w.isupper()) / len(words) > 0.7:
            return []
    return keep


def _nice_date(yyyymmdd: str | None) -> str | None:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return None
    try:
        d = date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
        return f"{d.day} {d.strftime('%b %Y')}"
    except ValueError:
        return None


def clean_overview(raw: str | None, uploader: str | None, upload_date: str | None, limit: int = 480) -> str:
    header = " · ".join(x for x in (uploader, _nice_date(upload_date)) if x)
    parts: list[str] = []
    for idx, para in enumerate(re.split(r"\n\s*\n", (raw or "").replace("\r", ""))):
        lines = _prose_lines(para)
        if not lines:
            continue
        text = " ".join(lines)
        if len(text) < 60 and not (idx == 0 and _SENTENCE_RE.search(text) and len(text) >= 25):
            continue
        parts.append(text)
        if sum(len(b) for b in parts) >= 120:
            break
    body = "\n\n".join(parts)
    if len(body) > limit:
        cut = body[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        body = cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…"
    return (header + ("\n\n" + body if body else "")).strip()


# --- nfo -----------------------------------------------------------------------------
def _xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def episode_nfo(title: str, show: str, season: int, episode: int, plot: str | None, aired: str | None,
                year: int | None, youtube_id: str | None, uploader: str | None) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8" standalone="yes"?>', "<episodedetails>",
             f"  <title>{_xml(title)}</title>", f"  <showtitle>{_xml(show)}</showtitle>",
             f"  <season>{season}</season>", f"  <episode>{episode}</episode>"]
    if plot:
        lines.append(f"  <plot>{_xml(plot)}</plot>")
    if aired:
        lines.append(f"  <aired>{_xml(aired)}</aired>")
    if year:
        lines.append(f"  <year>{year}</year>")
    if uploader:
        lines.append(f"  <studio>{_xml(uploader)}</studio>")
    lines.append(f"  <sorttitle>{_xml(title)}</sorttitle>")
    if youtube_id:
        lines.append(f'  <uniqueid type="YoutubeMetadata" default="true">{_xml(youtube_id)}</uniqueid>')
    lines += ["  <lockdata>false</lockdata>", "</episodedetails>", ""]
    return "\n".join(lines)


def write_sidecars(staging: Path, show: str, season: int, episode: int) -> list[Path]:
    written: list[Path] = []
    videos = sorted(p for p in staging.iterdir() if p.suffix.lower() in MEDIA_EXTS)
    for i, video in enumerate(videos):
        stem = video.with_suffix("")
        info_path = Path(str(stem) + ".info.json")
        info = json.loads(info_path.read_text()) if info_path.exists() else {}
        m = re.search(r"\[([A-Za-z0-9_-]{11})\]", video.name)
        vid = info.get("id") or (m.group(1) if m else None)
        title = info.get("title") or video.stem.split(" - ", 1)[-1]
        uploader = info.get("uploader") or info.get("channel")
        upload_date = info.get("upload_date")  # YYYYMMDD
        aired = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}" if upload_date and len(upload_date) >= 8 else None
        year = int(upload_date[:4]) if upload_date and upload_date[:4].isdigit() else None
        plot = clean_overview(info.get("description"), uploader, upload_date)
        nfo = Path(str(stem) + ".nfo")
        nfo.write_text(episode_nfo(title, show, season, episode + i, plot, aired, year, vid, uploader))
        written.append(nfo)
        for ext in (".jpg", ".jpeg", ".webp", ".png"):
            img = Path(str(stem) + ext)
            if img.exists():
                img.rename(Path(str(stem) + "-thumb" + ext))
                break
        if info_path.exists():
            info_path.unlink()
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("usage: jellyfin_nfo.py <staging_dir> <show> <season> <episode>", file=sys.stderr)
        return 2
    staging, show, season, episode = Path(argv[1]), argv[2], int(argv[3]), int(argv[4])
    if not staging.is_dir():
        print(f"not a directory: {staging}", file=sys.stderr)
        return 1
    for p in write_sidecars(staging, show, season, episode):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
