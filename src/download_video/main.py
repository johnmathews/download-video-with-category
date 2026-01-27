#!/usr/bin/env python3
"""Download YouTube videos with subtitles, thumbnails, and metadata."""

import sys
from pathlib import Path

import yt_dlp


def get_ydl_opts(output_dir: Path, subtitle_langs: list[str] | None = None) -> dict:
    """Build yt-dlp options dictionary."""
    opts = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mkv",
        "writethumbnail": True,
        "embedthumbnail": True,
        "writedescription": True,
        "writeinfojson": True,
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
    }

    if subtitle_langs:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = subtitle_langs

    return opts


def main():
    if len(sys.argv) < 2:
        print("Usage: yt <youtube-url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    output_dir = Path.home() / "Desktop" / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try with all subtitle languages first, fall back if rate limited
    subtitle_configs = [
        ["en", "nl"],  # Try both languages
        ["en"],  # Fall back to English only
        None,  # Fall back to no subtitles
    ]

    for langs in subtitle_configs:
        ydl_opts = get_ydl_opts(output_dir, langs)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            break  # Success, exit loop
        except yt_dlp.utils.DownloadError as e:
            if "429" in str(e) and langs:
                lang_str = ", ".join(langs)
                print(f"Rate limited on subtitles ({lang_str}), retrying with fewer...", file=sys.stderr)
                continue
            raise


if __name__ == "__main__":
    main()
