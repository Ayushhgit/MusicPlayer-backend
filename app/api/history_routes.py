"""
Listening History API routes.
Tracks play events and provides recently played, most played, and user stats.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from pydantic import BaseModel
from typing import Optional

from app.database.db import get_session
from app.database.models import ListeningHistory
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/history", tags=["History"])


class PlayEventRequest(BaseModel):
    video_id: str
    title: str
    channel: Optional[str] = "Unknown"
    thumbnail: Optional[str] = ""
    duration: Optional[str] = "0:00"


@router.post("")
async def log_play_event(req: PlayEventRequest, db: AsyncSession = Depends(get_session)):
    """Log a new play event to listening history."""
    try:
        entry = ListeningHistory(
            video_id=req.video_id,
            title=req.title,
            channel=req.channel,
            thumbnail=req.thumbnail,
            duration=req.duration,
        )
        db.add(entry)
        await db.commit()
        return {"status": "ok", "message": "Play event logged"}
    except Exception as e:
        await db.rollback()
        logger.error("Failed to log play event: %s", e)
        raise HTTPException(status_code=500, detail="Could not log play event")


@router.get("/recent")
async def get_recently_played(
    limit: int = Query(default=20, le=50),
    db: AsyncSession = Depends(get_session)
):
    """Get the last N unique songs played, most recent first."""
    try:
        # Subquery: get the latest play time for each unique video_id
        sub = (
            select(
                ListeningHistory.video_id,
                func.max(ListeningHistory.played_at).label("latest_play")
            )
            .group_by(ListeningHistory.video_id)
            .subquery()
        )
        # Join back to get full metadata
        stmt = (
            select(ListeningHistory)
            .join(sub, (ListeningHistory.video_id == sub.c.video_id) & (ListeningHistory.played_at == sub.c.latest_play))
            .order_by(desc(sub.c.latest_play))
            .limit(limit)
        )
        result = await db.execute(stmt)
        songs = result.scalars().all()
        return {
            "results": [
                {
                    "video_id": s.video_id,
                    "title": s.title,
                    "channel": s.channel,
                    "thumbnail": s.thumbnail,
                    "duration": s.duration,
                    "played_at": s.played_at.isoformat() if s.played_at else None,
                }
                for s in songs
            ]
        }
    except Exception as e:
        logger.error("Failed to fetch recently played: %s", e)
        raise HTTPException(status_code=500, detail="Database failure")


@router.get("/most-played")
async def get_most_played(
    limit: int = Query(default=20, le=50),
    db: AsyncSession = Depends(get_session)
):
    """Get top songs by play count."""
    try:
        stmt = (
            select(
                ListeningHistory.video_id,
                ListeningHistory.title,
                ListeningHistory.channel,
                ListeningHistory.thumbnail,
                ListeningHistory.duration,
                func.count(ListeningHistory.id).label("play_count"),
                func.max(ListeningHistory.played_at).label("last_played"),
            )
            .group_by(ListeningHistory.video_id)
            .order_by(desc("play_count"))
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return {
            "results": [
                {
                    "video_id": r.video_id,
                    "title": r.title,
                    "channel": r.channel,
                    "thumbnail": r.thumbnail,
                    "duration": r.duration,
                    "play_count": r.play_count,
                    "last_played": r.last_played.isoformat() if r.last_played else None,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error("Failed to fetch most played: %s", e)
        raise HTTPException(status_code=500, detail="Database failure")


@router.get("/stats")
async def get_user_stats(db: AsyncSession = Depends(get_session)):
    """Get aggregate user listening statistics."""
    try:
        total_plays_result = await db.execute(select(func.count(ListeningHistory.id)))
        total_plays = total_plays_result.scalar() or 0

        unique_songs_result = await db.execute(
            select(func.count(func.distinct(ListeningHistory.video_id)))
        )
        unique_songs = unique_songs_result.scalar() or 0

        return {
            "total_plays": total_plays,
            "unique_songs": unique_songs,
        }
    except Exception as e:
        logger.error("Failed to get stats: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get stats")
