"""
Custom Playlist Collection routes.
Full CRUD + Spotify import + reorder + duplicate detection + stats.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from pydantic import BaseModel
from typing import List, Optional

from app.database.db import get_session
from app.database.models import PlaylistCollection, CollectionItem
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/collections", tags=["Custom Playlists"])


# ── Request schemas ───────────────────────────────────────────────────────────

class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None

class CollectionItemCreate(BaseModel):
    video_id: str
    title: str
    channel: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[str] = "0:00"

class ReorderRequest(BaseModel):
    """List of video_ids in the desired order."""
    order: List[str]

class SpotifyImportRequest(BaseModel):
    url: str


# ── Collection CRUD ───────────────────────────────────────────────────────────

@router.get("")
async def get_collections(
    sort_by: str = Query(default="recent", pattern="^(recent|name)$"),
    db: AsyncSession = Depends(get_session)
):
    """Fetch all collections with song counts."""
    try:
        # Subquery for song count per collection
        count_sub = (
            select(
                CollectionItem.collection_id,
                func.count(CollectionItem.id).label("song_count")
            )
            .group_by(CollectionItem.collection_id)
            .subquery()
        )

        stmt = (
            select(PlaylistCollection, count_sub.c.song_count)
            .outerjoin(count_sub, PlaylistCollection.id == count_sub.c.collection_id)
        )

        if sort_by == "name":
            stmt = stmt.order_by(PlaylistCollection.name)
        else:
            stmt = stmt.order_by(PlaylistCollection.created_at.desc())

        result = await db.execute(stmt)
        rows = result.all()

        return {
            "results": [
                {
                    "id": col.id,
                    "name": col.name,
                    "description": col.description or "",
                    "cover_url": col.cover_url or "",
                    "created_at": col.created_at.isoformat() if col.created_at else None,
                    "song_count": song_count or 0,
                }
                for col, song_count in rows
            ]
        }
    except Exception as e:
        logger.error("Failed to fetch collections: %s", e)
        raise HTTPException(status_code=500, detail="Database failure")


@router.get("/{collection_id}")
async def get_collection_detail(collection_id: int, db: AsyncSession = Depends(get_session)):
    """Get a single collection with detailed stats."""
    try:
        result = await db.execute(select(PlaylistCollection).where(PlaylistCollection.id == collection_id))
        col = result.scalar_one_or_none()
        if not col:
            raise HTTPException(status_code=404, detail="Playlist not found")

        count_result = await db.execute(
            select(func.count(CollectionItem.id)).where(CollectionItem.collection_id == collection_id)
        )
        song_count = count_result.scalar() or 0

        return {
            "id": col.id,
            "name": col.name,
            "description": col.description or "",
            "cover_url": col.cover_url or "",
            "created_at": col.created_at.isoformat() if col.created_at else None,
            "song_count": song_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch collection detail: %s", e)
        raise HTTPException(status_code=500, detail="Database failure")


@router.post("")
async def create_collection(data: CollectionCreate, db: AsyncSession = Depends(get_session)):
    """Create a new custom playlist."""
    try:
        new_col = PlaylistCollection(name=data.name, description=data.description or "")
        db.add(new_col)
        await db.commit()
        await db.refresh(new_col)
        return {"message": "Playlist created", "collection": {"id": new_col.id, "name": new_col.name}}
    except Exception as e:
        await db.rollback()
        logger.error("Failed to create collection: %s", e)
        raise HTTPException(status_code=500, detail="Could not create playlist")


@router.patch("/{collection_id}")
async def update_collection(collection_id: int, data: CollectionUpdate, db: AsyncSession = Depends(get_session)):
    """Update playlist name, description, or cover image."""
    try:
        result = await db.execute(select(PlaylistCollection).where(PlaylistCollection.id == collection_id))
        col = result.scalar_one_or_none()
        if not col:
            raise HTTPException(status_code=404, detail="Playlist not found")

        if data.name is not None:
            col.name = data.name
        if data.description is not None:
            col.description = data.description
        if data.cover_url is not None:
            col.cover_url = data.cover_url

        await db.commit()
        return {"message": "Playlist updated"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Failed to update collection: %s", e)
        raise HTTPException(status_code=500, detail="Could not update playlist")


@router.delete("/{collection_id}")
async def delete_collection(collection_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a custom playlist and all nested songs."""
    try:
        result = await db.execute(select(PlaylistCollection).where(PlaylistCollection.id == collection_id))
        target_col = result.scalar_one_or_none()
        if not target_col:
            raise HTTPException(status_code=404, detail="Playlist not found")

        items_res = await db.execute(select(CollectionItem).where(CollectionItem.collection_id == collection_id))
        for item in items_res.scalars().all():
            await db.delete(item)

        await db.delete(target_col)
        await db.commit()
        return {"message": "Playlist deleted"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Failed to delete collection: %s", e)
        raise HTTPException(status_code=500, detail="Server Error")


# ── Collection Songs ──────────────────────────────────────────────────────────

@router.get("/{collection_id}/songs")
async def get_collection_songs(
    collection_id: int,
    sort_by: str = Query(default="order", pattern="^(order|recent|name|duration)$"),
    db: AsyncSession = Depends(get_session)
):
    """Fetch songs in a collection with sorting options."""
    try:
        stmt = select(CollectionItem).where(CollectionItem.collection_id == collection_id)

        if sort_by == "name":
            stmt = stmt.order_by(CollectionItem.title)
        elif sort_by == "recent":
            stmt = stmt.order_by(CollectionItem.added_at.desc())
        elif sort_by == "duration":
            stmt = stmt.order_by(CollectionItem.duration)
        else:
            stmt = stmt.order_by(CollectionItem.sort_order, CollectionItem.added_at.desc())

        result = await db.execute(stmt)
        songs = result.scalars().all()
        return {
            "results": [
                {
                    "id": s.id,
                    "video_id": s.video_id,
                    "title": s.title,
                    "channel": s.channel,
                    "thumbnail": s.thumbnail,
                    "duration": s.duration,
                    "sort_order": s.sort_order,
                }
                for s in songs
            ]
        }
    except Exception as e:
        logger.error("Failed to fetch collection songs: %s", e)
        raise HTTPException(status_code=500, detail="Database failure")


@router.post("/{collection_id}/songs")
async def add_song_to_collection(collection_id: int, song_data: CollectionItemCreate, db: AsyncSession = Depends(get_session)):
    """Add a song to a collection. Prevents duplicates."""
    try:
        # Verify collection exists
        col_check = await db.execute(select(PlaylistCollection).where(PlaylistCollection.id == collection_id))
        if not col_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Playlist not found")

        # Duplicate detection
        existing = await db.execute(
            select(CollectionItem)
            .where(CollectionItem.video_id == song_data.video_id)
            .where(CollectionItem.collection_id == collection_id)
        )
        if existing.scalar_one_or_none():
            return {"message": "Song already in this playlist", "duplicate": True}

        # Get next sort order
        max_order_result = await db.execute(
            select(func.max(CollectionItem.sort_order)).where(CollectionItem.collection_id == collection_id)
        )
        max_order = max_order_result.scalar() or 0

        new_item = CollectionItem(
            collection_id=collection_id,
            video_id=song_data.video_id,
            title=song_data.title,
            channel=song_data.channel,
            thumbnail=song_data.thumbnail,
            duration=song_data.duration,
            sort_order=max_order + 1,
        )
        db.add(new_item)
        await db.commit()
        await db.refresh(new_item)
        return {"message": "Song added", "duplicate": False}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Failed to add song: %s", e)
        raise HTTPException(status_code=500, detail="Could not add song")


@router.delete("/{collection_id}/songs/{video_id}")
async def remove_song_from_collection(collection_id: int, video_id: str, db: AsyncSession = Depends(get_session)):
    """Remove a song from a collection."""
    try:
        result = await db.execute(
            select(CollectionItem)
            .where(CollectionItem.video_id == video_id)
            .where(CollectionItem.collection_id == collection_id)
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="Song not found")

        await db.delete(target)
        await db.commit()
        return {"message": "Song removed"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Failed to remove song: %s", e)
        raise HTTPException(status_code=500, detail="Server error")


@router.put("/{collection_id}/songs/reorder")
async def reorder_collection_songs(collection_id: int, data: ReorderRequest, db: AsyncSession = Depends(get_session)):
    """Reorder songs within a collection by providing video_ids in desired order."""
    try:
        for idx, video_id in enumerate(data.order):
            await db.execute(
                update(CollectionItem)
                .where(CollectionItem.collection_id == collection_id)
                .where(CollectionItem.video_id == video_id)
                .values(sort_order=idx)
            )
        await db.commit()
        return {"message": "Playlist reordered"}
    except Exception as e:
        await db.rollback()
        logger.error("Failed to reorder: %s", e)
        raise HTTPException(status_code=500, detail="Reorder failed")


@router.post("/{target_collection_id}/songs/move/{video_id}/from/{source_collection_id}")
async def move_song_between_collections(
    target_collection_id: int, video_id: str, source_collection_id: int,
    db: AsyncSession = Depends(get_session)
):
    """Move a song from one collection to another."""
    try:
        # Find in source
        result = await db.execute(
            select(CollectionItem)
            .where(CollectionItem.video_id == video_id)
            .where(CollectionItem.collection_id == source_collection_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Song not found in source playlist")

        # Check duplicate in target
        dup_check = await db.execute(
            select(CollectionItem)
            .where(CollectionItem.video_id == video_id)
            .where(CollectionItem.collection_id == target_collection_id)
        )
        if dup_check.scalar_one_or_none():
            return {"message": "Song already exists in target playlist"}

        # Move
        item.collection_id = target_collection_id
        await db.commit()
        return {"message": "Song moved successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Failed to move song: %s", e)
        raise HTTPException(status_code=500, detail="Move failed")


# ── Spotify Import ────────────────────────────────────────────────────────────

@router.post("/import-spotify")
async def import_spotify_playlist(data: SpotifyImportRequest, db: AsyncSession = Depends(get_session)):
    """
    Import a Spotify playlist by URL.
    Creates a new collection and populates it with YouTube-matched songs.
    """
    from app.services.spotify_import_service import import_spotify_playlist as do_import
    from app.utils.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    
    logger.info("Importing Spotify Playlist with Client ID: %s", bool(SPOTIFY_CLIENT_ID))

    try:
        result = await do_import(data.url, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Spotify import failed: %s", e)
        raise HTTPException(status_code=500, detail="Import failed. Check the URL and try again.")

    # Create collection
    try:
        new_col = PlaylistCollection(
            name=result["playlist_name"],
            description=f"Imported from Spotify ({result['matched_tracks']}/{result['total_tracks']} tracks matched)"
        )
        db.add(new_col)
        await db.commit()
        await db.refresh(new_col)

        # Add matched songs
        for idx, song in enumerate(result["songs"]):
            item = CollectionItem(
                collection_id=new_col.id,
                video_id=song["video_id"],
                title=song["title"],
                channel=song.get("channel"),
                thumbnail=song.get("thumbnail"),
                duration=song.get("duration", "0:00"),
                sort_order=idx,
            )
            db.add(item)

        await db.commit()

        return {
            "message": f"Imported '{result['playlist_name']}' with {result['matched_tracks']}/{result['total_tracks']} tracks",
            "collection_id": new_col.id,
            "playlist_name": result["playlist_name"],
            "matched": result["matched_tracks"],
            "total": result["total_tracks"],
        }
    except Exception as e:
        await db.rollback()
        logger.error("Failed to save imported playlist: %s", e)
        raise HTTPException(status_code=500, detail="Import succeeded but save failed")
