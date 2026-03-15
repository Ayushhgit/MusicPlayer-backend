"""
Search API routes.
Provides /search, /search/suggestions, and /trending endpoints.
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query

from app.services.youtube_service import search_videos
from app.services.redis_service import get_cache, set_cache
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Search"])


@router.get("/search")
async def search(q: str = Query(..., min_length=1, description="Search query")):
    """
    Search YouTube for songs.
    Returns up to 10 results with full metadata.
    Triggers background pre-warming for top 2 results.
    """
    try:
        results = await search_videos(q)

        # Trigger background pre-warming for top 2
        from app.workers.pre_warming_worker import prewarm
        video_ids = [r["video_id"] for r in results if "video_id" in r]

        async def prewarm_top2(v_ids):
            top2 = v_ids[:2]
            await prewarm(top2)

        asyncio.create_task(prewarm_top2(video_ids))

        return {"results": results}
    except Exception as exc:
        logger.error("Search endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail="Search failed. Please try again.")


@router.get("/search/suggestions")
async def search_suggestions(q: str = Query(..., min_length=1)):
    """
    Return quick search suggestions based on partial query.
    Uses YouTube search but returns only titles for autocomplete.
    """
    try:
        cache_key = f"suggest:{q}"
        cached = await get_cache(cache_key)
        if cached:
            return {"suggestions": json.loads(cached)}

        results = await search_videos(q)
        suggestions = [r["title"] for r in results[:5]]

        await set_cache(cache_key, json.dumps(suggestions), expire=1800)
        return {"suggestions": suggestions}
    except Exception as exc:
        logger.error("Suggestions error: %s", exc)
        return {"suggestions": []}


@router.get("/trending")
async def get_trending():
    """
    Get trending music from YouTube.
    Cached for 30 minutes to avoid excessive YouTube requests.
    """
    try:
        cache_key = "trending:music"
        cached = await get_cache(cache_key)
        if cached:
            return {"results": json.loads(cached)}

        # Search for currently trending/popular music
        results = await search_videos("trending music 2025")

        await set_cache(cache_key, json.dumps(results), expire=1800)
        return {"results": results}
    except Exception as exc:
        logger.error("Trending endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail="Could not fetch trending")
