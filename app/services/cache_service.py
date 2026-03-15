"""
Cache service for managing locally stored songs.
Provides check, registration, and retrieval operations against the SQLite DB.
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import async_session
from app.database.models import Song
from app.utils.config import SONGS_DIR
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def is_cached(video_id: str) -> bool:
    """
    Check if a song is cached (exists in DB AND on disk).

    Args:
        video_id: YouTube video ID.

    Returns:
        True if the song file exists locally and is registered in the DB.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Song).where(Song.video_id == video_id)
        )
        song = result.scalar_one_or_none()

    if song is None:
        logger.info("Cache MISS for video_id=%s (not in DB)", video_id)
        return False
        
    file_path = Path(song.file_path)
    if not file_path.exists():
        logger.info("Cache MISS for video_id=%s (in DB but file missing)", video_id)
        return False

    logger.info("Cache HIT for video_id=%s", video_id)
    return True


async def register_download(video_id: str, title: str, file_path: str) -> None:
    """
    Register a newly downloaded song in the database.

    Args:
        video_id: YouTube video ID.
        title: Song title.
        file_path: Absolute local path to the registered audio file.
    """
    async with async_session() as session:
        existing = await session.execute(
            select(Song).where(Song.video_id == video_id)
        )
        if existing.scalar_one_or_none():
            logger.debug("Song %s already registered in DB, skipping.", video_id)
            return

        song = Song(video_id=video_id, title=title, file_path=file_path)
        session.add(song)
        await session.commit()
        logger.info("Registered download: video_id=%s title=%s", video_id, title)


async def get_local_path(video_id: str) -> str | None:
    """
    Get the local file path for a cached song.

    Args:
        video_id: YouTube video ID.

    Returns:
        The relative URL path (e.g. /local/SongTitle.mp3) or None.
    """
    if await is_cached(video_id):
        async with async_session() as session:
            result = await session.execute(
                select(Song).where(Song.video_id == video_id)
            )
            song = result.scalar_one_or_none()
            if song:
                filename = Path(song.file_path).name
                return f"/local/{filename}"
    return None
