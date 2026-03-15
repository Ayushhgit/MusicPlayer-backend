"""
Stream & Cache Management API routes.
Provides streaming, download, cache clearing, and storage management.
"""

import asyncio
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.stream_service import get_stream_info
from app.workers.background_downloader import background_download
from app.services.redis_service import get_redis_client
from app.utils.config import SONGS_DIR, MAX_CACHE_SIZE_MB
from app.database.db import get_session
from app.database.models import Playlist, CollectionItem
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Stream & Cache"])


# ── Streaming ─────────────────────────────────────────────────────────────────

@router.get("/stream/{video_id}")
async def stream(video_id: str = PathParam(..., description="YouTube video ID")):
    """
    Get the streaming URL for a song.
    Checks local cache → Redis → YouTube, triggers background download.
    """
    try:
        info = await get_stream_info(video_id)
    except ValueError as exc:
        logger.warning("Stream error for %s: %s", video_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Stream endpoint error for %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail="Failed to get stream.")

    return info


@router.get("/stream/proxy/{video_id}")
async def proxy_stream(video_id: str = PathParam(..., description="YouTube video ID")):
    """
    Proxy an audio stream from YouTube directly to the client.
    Used for downloading songs to the phone's local storage.
    """
    try:
        info = await get_stream_info(video_id)
        audio_url = info.get("url")
        if not audio_url:
            raise HTTPException(status_code=404, detail="Audio URL not found.")

        async def stream_audio():
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", audio_url) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk

        return StreamingResponse(
            stream_audio(),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{video_id}.mp3"'
            }
        )
    except Exception as exc:
        logger.error("Proxy stream error for %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail="Failed to proxy stream.")


@router.post("/download/{video_id}")
async def download_song(video_id: str = PathParam(..., description="YouTube video ID")):
    """Manually trigger a background download for caching."""
    try:
        info = await get_stream_info(video_id)
        title = info.get("title", "Unknown")

        logger.info("Manually triggering download for %s", video_id)
        asyncio.create_task(background_download(video_id, title))

        return {"status": "started", "message": f"Download initiated for {title}"}
    except Exception as exc:
        logger.error("Download error for %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail="Failed to start download.")


# ── Cache Management ──────────────────────────────────────────────────────────

@router.delete("/cache/{video_id}")
async def clear_cache(video_id: str = PathParam(..., description="YouTube video ID")):
    """Clear Redis cache for a specific stream."""
    try:
        r_client = await get_redis_client()
        if r_client:
            await r_client.delete(f"stream:{video_id}")
            logger.info("Cleared cache for %s", video_id)
        return {"status": "cleared"}
    except Exception as exc:
        logger.error("Cache clear error: %s", exc)
        return {"status": "error"}


@router.get("/cache/status")
async def get_cache_status():
    """
    Get local cache storage status.
    Returns number of cached files, total disk usage, and configured limit.
    """
    try:
        songs_path = Path(SONGS_DIR)
        if not songs_path.exists():
            return {
                "cached_files": 0,
                "total_size_mb": 0,
                "max_size_mb": MAX_CACHE_SIZE_MB,
                "usage_percent": 0,
            }

        files = list(songs_path.glob("*.m4a")) + list(songs_path.glob("*.mp3")) + list(songs_path.glob("*.webm"))
        total_bytes = sum(f.stat().st_size for f in files)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        usage_pct = round((total_mb / MAX_CACHE_SIZE_MB) * 100, 1) if MAX_CACHE_SIZE_MB > 0 else 0

        return {
            "cached_files": len(files),
            "total_size_mb": total_mb,
            "max_size_mb": MAX_CACHE_SIZE_MB,
            "usage_percent": usage_pct,
        }
    except Exception as exc:
        logger.error("Cache status error: %s", exc)
        return {"cached_files": 0, "total_size_mb": 0, "max_size_mb": MAX_CACHE_SIZE_MB, "usage_percent": 0}


@router.post("/cache/cleanup")
async def cleanup_cache():
    """
    Remove orphaned cache files and evict least-recently-used songs
    if storage exceeds the configured limit.
    """
    try:
        songs_path = Path(SONGS_DIR)
        if not songs_path.exists():
            return {"removed": 0, "freed_mb": 0}

        files = list(songs_path.glob("*.m4a")) + list(songs_path.glob("*.mp3")) + list(songs_path.glob("*.webm"))
        total_bytes = sum(f.stat().st_size for f in files)
        total_mb = total_bytes / (1024 * 1024)

        removed = 0
        freed_bytes = 0

        if total_mb > MAX_CACHE_SIZE_MB and MAX_CACHE_SIZE_MB > 0:
            # Sort by access time (oldest first) for LRU eviction
            files_sorted = sorted(files, key=lambda f: f.stat().st_atime)

            for f in files_sorted:
                if total_mb - (freed_bytes / (1024 * 1024)) <= MAX_CACHE_SIZE_MB * 0.8:
                    break  # Stop when we're at 80% capacity
                size = f.stat().st_size
                f.unlink()
                freed_bytes += size
                removed += 1
                logger.info("Evicted cache file: %s", f.name)

        return {
            "removed": removed,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        }
    except Exception as exc:
        logger.error("Cache cleanup error: %s", exc)
        raise HTTPException(status_code=500, detail="Cleanup failed")

# ── Pre-cache Library (Redis stream URLs only) ────────────────────────────────

async def _precache_stream_url(video_id: str) -> None:
    """Pre-warm the Redis cache with a stream URL for a single video."""
    from app.services.redis_service import get_cache, set_cache
    
    redis_key = f"stream:{video_id}"
    existing = await get_cache(redis_key)
    if existing:
        return  # Already cached in Redis
    
    try:
        from app.workers.pre_warming_worker import extract_audio_url
        loop = asyncio.get_event_loop()
        audio_url = await loop.run_in_executor(None, extract_audio_url, video_id)
        if audio_url:
            await set_cache(redis_key, audio_url, expire=3000)
            logger.info("Pre-cached stream URL for %s", video_id)
    except Exception as e:
        logger.warning("Failed to pre-cache %s: %s", video_id, e)


@router.post("/cache/precache-library")
async def precache_library(db: AsyncSession = Depends(get_session)):
    """
    Pre-cache stream URLs for all Liked Songs and playlist songs in Redis.
    Does NOT download files — just warms the URL cache for instant playback.
    """
    try:
        # Gather all unique video_ids from liked songs + playlists
        liked_stmt = select(Playlist.video_id, Playlist.title)
        liked_result = await db.execute(liked_stmt)
        liked_songs = liked_result.all()

        collection_stmt = select(CollectionItem.video_id, CollectionItem.title)
        collection_result = await db.execute(collection_stmt)
        collection_songs = collection_result.all()

        # Deduplicate
        all_video_ids: set[str] = set()
        for vid, _ in liked_songs:
            all_video_ids.add(vid)
        for vid, _ in collection_songs:
            all_video_ids.add(vid)

        # Check which are already cached in Redis
        from app.services.redis_service import get_cache
        already_cached = 0
        to_cache: list[str] = []
        for vid in all_video_ids:
            existing = await get_cache(f"stream:{vid}")
            if existing:
                already_cached += 1
            else:
                to_cache.append(vid)

        logger.info(
            "Pre-cache: %d library songs, %d already in Redis, %d to warm",
            len(all_video_ids), already_cached, len(to_cache),
        )

        # Fire background tasks to warm Redis (no file downloads)
        for vid in to_cache:
            asyncio.create_task(_precache_stream_url(vid))

        return {
            "total_library_songs": len(all_video_ids),
            "already_cached": already_cached,
            "warming_started": len(to_cache),
            "message": f"Warming {len(to_cache)} stream URLs in background.",
        }

    except Exception as exc:
        logger.error("Pre-cache error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to start pre-caching.")


