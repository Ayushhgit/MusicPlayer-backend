"""
YouTube search service.
Uses yt-dlp's built-in ytsearch to find videos — more reliable than
third-party wrappers that break on httpx/API changes.
"""

import asyncio
from typing import Any

import yt_dlp

from app.utils.config import MAX_SEARCH_RESULTS
from app.utils.logger import get_logger

logger = get_logger(__name__)

# yt-dlp options for search/extract_info (no download)
_SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": True,           # don't resolve every video
    "default_search": "ytsearch",   # use YouTube search
}


async def search_videos(query: str) -> list[dict[str, Any]]:
    """
    Search YouTube for videos matching the query using yt-dlp.
    Checks Redis cache first, avoiding expensive search extraction if cached.

    Args:
        query: The search string.

    Returns:
        A list of up to MAX_SEARCH_RESULTS result dicts.
    """
    logger.info("Searching YouTube for: %s", query)
    
    # 1. Check Redis Cache
    from app.services.redis_service import get_cache, set_cache
    import json
    
    cache_key = f"search:{query}"
    cached_result = await get_cache(cache_key)
    if cached_result:
        logger.info("Serving search from Redis cache for: %s", query)
        try:
            return json.loads(cached_result)
        except json.JSONDecodeError:
            pass

    # 2. Perform background extraction
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(None, _blocking_search, query)
    except Exception as exc:
        logger.error("YouTube search failed for query '%s': %s", query, exc)
        raise

    logger.info("Found %d results for: %s", len(results), query)
    
    # 3. Cache the results for 1 hour (3600 seconds)
    await set_cache(cache_key, json.dumps(results), expire=3000)
    
    return results


def _blocking_search(query: str) -> list[dict[str, Any]]:
    """Synchronous yt-dlp search (runs in executor)."""
    search_query = f"ytsearch{MAX_SEARCH_RESULTS}:{query}"

    with yt_dlp.YoutubeDL(_SEARCH_OPTS) as ydl:
        info = ydl.extract_info(search_query, download=False)

    entries = info.get("entries", []) if info else []
    results = []

    for item in entries:
        if not item:
            continue

        # Duration can be seconds (int) or a string
        duration_raw = item.get("duration")
        if isinstance(duration_raw, (int, float)) and duration_raw:
            mins, secs = divmod(int(duration_raw), 60)
            duration = f"{mins}:{secs:02d}"
        else:
            duration = str(duration_raw) if duration_raw else "N/A"

        # View count
        view_count = item.get("view_count")
        if view_count is not None:
            if view_count >= 1_000_000:
                views = f"{view_count / 1_000_000:.1f}M views"
            elif view_count >= 1_000:
                views = f"{view_count / 1_000:.1f}K views"
            else:
                views = f"{view_count} views"
        else:
            views = "N/A"

        # Thumbnail — yt-dlp flat extract may or may not have thumbnails
        thumbnails = item.get("thumbnails", [])
        thumbnail = thumbnails[-1]["url"] if thumbnails else (
            f"https://i.ytimg.com/vi/{item.get('id', '')}/hqdefault.jpg"
        )

        results.append(
            {
                "title": item.get("title", "Unknown"),
                "video_id": item.get("id", item.get("url", "")),
                "thumbnail": thumbnail,
                "channel": item.get("channel", item.get("uploader", "Unknown")),
                "duration": duration,
                "views": views,
            }
        )

    return results
