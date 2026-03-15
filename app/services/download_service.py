"""
Download service.
Downloads audio from YouTube using yt-dlp, converts to MP3,
and registers the result in the cache database.
"""

import asyncio
import re
from typing import Set

import yt_dlp

from app.services.cache_service import is_cached, register_download
from app.utils.config import SONGS_DIR, YTDLP_OPTIONS
from app.utils.logger import get_logger

logger = get_logger(__name__)

# In-memory lock to prevent duplicate concurrent downloads
_active_downloads: Set[str] = set()
_lock = asyncio.Lock()


def get_safe_filename(title: str) -> str:
    """Generate a safe filename from the song title."""
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()


async def download_song(video_id: str, title: str = "Unknown") -> bool:
    """
    Download a song from YouTube and save as MP3.

    Uses an in-memory lock set to prevent duplicate concurrent downloads.

    Args:
        video_id: YouTube video ID.
        title: Song title for DB registration.

    Returns:
        True if download succeeded (or was already cached), False on error.
    """
    # Skip if already cached
    if await is_cached(video_id):
        logger.info("Song %s already cached, skipping download.", video_id)
        return True

    # Acquire lock to check/set active downloads
    async with _lock:
        if video_id in _active_downloads:
            logger.info("Download already in progress for %s, skipping.", video_id)
            return True
        _active_downloads.add(video_id)

    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info("Starting download: video_id=%s title=%s", video_id, title)

        safe_title = get_safe_filename(title)
        
        # We need to construct the opts for yt_dlp with the proper outtmpl
        opts = YTDLP_OPTIONS.copy()
        opts["outtmpl"] = str(SONGS_DIR / f"{safe_title}.%(ext)s")

        # Run yt-dlp in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _blocking_download, url, opts)

        # Register in the cache database
        file_path = str(SONGS_DIR / f"{safe_title}.mp3")
        await register_download(video_id, title, file_path)
        logger.info("Download complete: video_id=%s", video_id)
        return True

    except Exception as exc:
        logger.error("Download failed for %s: %s", video_id, exc)
        return False

    finally:
        async with _lock:
            _active_downloads.discard(video_id)


def _blocking_download(url: str, opts: dict) -> None:
    """Synchronous yt-dlp download (runs in executor)."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
