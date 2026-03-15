"""
Playlist API routes.
Provides CRUD endpoints for managing user's saved songs in the SQLite database.
"""

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database.db import get_session
from app.database.models import Playlist
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Playlist"])

class PlaylistAddRequest(BaseModel):
    video_id: str
    title: str
    channel: str = "Unknown"
    thumbnail: str = ""

@router.get("/playlist")
async def get_playlist(session: AsyncSession = Depends(get_session)):
    """Fetch all saved songs in the playlist, ordered by newest first."""
    try:
        stmt = select(Playlist).order_by(Playlist.added_at.desc())
        result = await session.execute(stmt)
        songs = result.scalars().all()
        return {
            "results": [
                {
                    "video_id": s.video_id,
                    "title": s.title,
                    "channel": s.channel,
                    "thumbnail": s.thumbnail
                }
                for s in songs
            ]
        }
    except Exception as exc:
        logger.error("Failed to fetch playlist: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load playlist")

@router.post("/playlist")
async def add_to_playlist(req: PlaylistAddRequest, session: AsyncSession = Depends(get_session)):
    """Add a song to the user's playlist."""
    try:
        # Check if already exists
        check_stmt = select(Playlist).where(Playlist.video_id == req.video_id)
        result = await session.execute(check_stmt)
        if result.scalar_one_or_none():
            return {"status": "success", "message": "Song already in playlist."}
            
        new_entry = Playlist(
            video_id=req.video_id,
            title=req.title,
            channel=req.channel,
            thumbnail=req.thumbnail
        )
        session.add(new_entry)
        await session.commit()
        return {"status": "success", "message": f"Added {req.title} to playlist."}
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to add to playlist for %s: %s", req.video_id, exc)
        raise HTTPException(status_code=500, detail="Failed to save to playlist")

@router.delete("/playlist/{video_id}")
async def remove_from_playlist(video_id: str = Path(...), session: AsyncSession = Depends(get_session)):
    """Remove a song from the user's playlist by video_id."""
    try:
        stmt = select(Playlist).where(Playlist.video_id == video_id)
        result = await session.execute(stmt)
        entry = result.scalar_one_or_none()
        
        if entry:
            await session.delete(entry)
            await session.commit()
            return {"status": "success", "message": "Removed from playlist."}
        return {"status": "success", "message": "Song was not in playlist."}
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to remove from playlist %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail="Failed to remove from playlist")
