"""
ORM models for the Auralux music streaming backend.
Covers: song cache, liked songs, custom playlists, listening history.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class Song(Base):
    """Represents a cached song downloaded from YouTube."""

    __tablename__ = "songs"

    video_id: Mapped[str] = mapped_column(String(20), primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Song video_id={self.video_id!r} title={self.title!r}>"


class Playlist(Base):
    """Represents a song saved to the user's Liked Songs."""

    __tablename__ = "playlist_songs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    channel: Mapped[str] = mapped_column(String(200), nullable=True)
    thumbnail: Mapped[str] = mapped_column(String(1000), nullable=True)
    duration: Mapped[str] = mapped_column(String(20), nullable=True, default="0:00")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Playlist video_id={self.video_id!r} title={self.title!r}>"


class PlaylistCollection(Base):
    """Represents a custom user playlist container."""

    __tablename__ = "playlist_collections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True, default="")
    cover_url: Mapped[str] = mapped_column(String(1000), nullable=True, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CollectionItem(Base):
    """Represents a song saved to a specific custom playlist."""

    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(index=True, nullable=False)
    video_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    channel: Mapped[str] = mapped_column(String(200), nullable=True)
    thumbnail: Mapped[str] = mapped_column(String(1000), nullable=True)
    duration: Mapped[str] = mapped_column(String(20), nullable=True, default="0:00")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ListeningHistory(Base):
    """Tracks every song play event for history and analytics."""

    __tablename__ = "listening_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    channel: Mapped[str] = mapped_column(String(200), nullable=True)
    thumbnail: Mapped[str] = mapped_column(String(1000), nullable=True)
    duration: Mapped[str] = mapped_column(String(20), nullable=True)
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<History video_id={self.video_id!r} played_at={self.played_at}>"
