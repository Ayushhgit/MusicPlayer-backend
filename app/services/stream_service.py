"""
Stream service.
Orchestrates the streaming flow:
  1. Check local cache → serve from disk.
  2. Otherwise extract direct audio URL via yt-dlp → return URL immediately.
  3. Trigger background download for future cache.
"""

import asyncio
from typing import Any

import yt_dlp

from app.services.cache_service import get_local_path
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_stream_info(video_id: str) -> dict[str, Any]:
    """
    Get the streaming information for a video.

    Returns a dict with:
      - source: "local", "redis", or "youtube"
      - url: the URL to play the audio from
      - title: the song title

    Args:
        video_id: YouTube video ID.

    Returns:
        Stream info dictionary.
    """
    # 1. Check local cache (SQLite + physical file)
    local_url = await get_local_path(video_id)
    if local_url:
        logger.info("Serving from local cache: %s", video_id)
        return {"source": "local", "url": local_url, "title": ""}

    # 2. Check Redis pre-warmed cache
    from app.services.redis_service import get_cache, set_cache, get_redis_client
    redis_key = f"stream:{video_id}"
    cached_url = await get_cache(redis_key)
    if cached_url:
        logger.info("Serving from Redis cache for: %s", video_id)
        return {"source": "redis", "url": cached_url, "title": ""}

    # 3. Fallback: Extract direct audio URL from YouTube (synchronized with lock)
    logger.info("Cache miss for %s. Attempting fallback extraction.", video_id)
    
    # Try to acquire an extraction lock to prevent 10 users requesting yt-dlp at once
    r_client = await get_redis_client()
    lock_key = f"lock:stream:{video_id}"
    lock_acquired = False
    
    if r_client:
        lock_acquired = await r_client.setnx(lock_key, "1")
        if lock_acquired:
            await r_client.expire(lock_key, 60) # Lock for 60 seconds
        else:
            # Another worker is extracting. We can poll for a few seconds.
            logger.info("Waiting for another worker to extract %s...", video_id)
            for _ in range(30): # Wait up to 15 seconds
                await asyncio.sleep(0.5)
                cached_url = await get_cache(redis_key)
                if cached_url:
                    logger.info("Serving from newly populated Redis cache for: %s", video_id)
                    return {"source": "redis", "url": cached_url, "title": ""}
            # If still nothing, proceed to extract anyway for this request to not fail entirely
    
    try:
        from app.workers.pre_warming_worker import extract_audio_url
        
        loop = asyncio.get_event_loop()
        audio_url = await loop.run_in_executor(None, extract_audio_url, video_id)
        
        if not audio_url:
            raise ValueError(f"No suitable audio stream found for video {video_id}")
            
        # Save to Redis for next time
        await set_cache(redis_key, audio_url, expire=3600)
        
        logger.info("Stream URL extracted and cached for %s", video_id)
        return {"source": "youtube", "url": audio_url, "title": "Unknown"}
        
    except Exception as exc:
        logger.error("Failed to extract info for %s: %s", video_id, exc)
        raise ValueError(f"Could not extract audio for video {video_id}") from exc
    finally:
        # Cleanup lock if we held it
        if lock_acquired and r_client:
            await r_client.delete(lock_key)


async def _extract_info(video_id: str) -> dict:
    """Extract video info without downloading (runs in executor)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    loop = asyncio.get_event_loop()

    def _extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    return await loop.run_in_executor(None, _extract)


def _pick_best_audio_url(info: dict) -> str | None:
    """Pick the best audio URL from extracted info."""
    # Direct URL on the info dict (when format already resolved)
    if info.get("url"):
        return info["url"]

    # Search through formats for audio-only streams
    formats = info.get("formats", [])
    audio_formats = [
        f for f in formats
        if f.get("acodec") != "none" and f.get("vcodec") in ("none", None)
    ]

    if audio_formats:
        # Pick highest bitrate audio
        best = max(audio_formats, key=lambda f: f.get("abr", 0) or 0)
        return best.get("url")

    # Fallback: any format with a URL
    if formats:
        return formats[-1].get("url")

    return None
