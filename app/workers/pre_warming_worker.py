"""
Pre-warming worker for caching streaming URLs.
Extracts audio URLs using yt-dlp in parallel via a global ThreadPool.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import yt_dlp

from app.services.redis_service import set_cache
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Global thread pool for yt-dlp extractions
executor = ThreadPoolExecutor(max_workers=10)


def extract_audio_url(video_id: str) -> str:
    """Synchronous extraction using yt-dlp."""
    url = f"https://youtube.com/watch?v={video_id}"
    
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # find the best format if 'url' not directly at root level
    if info.get("url"):
        return info["url"]
        
    formats = info.get("formats", [])
    audio_formats = [
        f for f in formats 
        if f.get("acodec") != "none" and f.get("vcodec") in ("none", None)
    ]
    if audio_formats:
        best = max(audio_formats, key=lambda f: f.get("abr", 0) or 0)
        return best.get("url", "")
    elif formats:
        return formats[-1].get("url", "")
        
    return ""


async def prewarm(video_ids: list[str]) -> None:
    """
    Run parallel async extractions for a list of video IDs
    and save them directly to Redis.
    """
    if not video_ids:
        return

    logger.info("Starting background pre-warming for %d videos", len(video_ids))
    loop = asyncio.get_running_loop()

    tasks = []
    for video_id in video_ids:
        # Schedule the blocking function in the global executor
        task = loop.run_in_executor(
            executor,
            extract_audio_url,
            video_id
        )
        tasks.append(task)

    # Run them all concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = 0
    # Store successful extractions in Redis
    for video_id, url in zip(video_ids, results):
        if isinstance(url, Exception):
            logger.warning("Pre-warm extraction failed for %s: %s", video_id, url)
            continue
            
        if url:
            # cache for 1 hour
            await set_cache(f"stream:{video_id}", url, expire=3600)
            success_count += 1

    logger.info("Pre-warming complete. Successfully cached %d/%d stream URLs", success_count, len(video_ids))
