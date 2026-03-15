"""
Background downloader worker.
Provides a safe async task wrapper around the download service
that catches all errors to never crash the server.
"""

import asyncio

from app.services.download_service import download_song
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def background_download(video_id: str, title: str = "Unknown") -> None:
    """
    Run a download in the background.

    This function is designed to be used with FastAPI BackgroundTasks
    or asyncio.create_task(). It catches all exceptions so the main
    server loop is never affected.

    Args:
        video_id: YouTube video ID to download.
        title: Song title for DB registration.
    """
    try:
        logger.info("Background download started: video_id=%s", video_id)
        success = await download_song(video_id, title)
        if success:
            logger.info("Background download succeeded: video_id=%s", video_id)
        else:
            logger.warning("Background download returned failure: video_id=%s", video_id)
    except Exception as exc:
        logger.error(
            "Background download crashed for video_id=%s: %s", video_id, exc
        )
