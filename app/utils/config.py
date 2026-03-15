"""
Centralized configuration for the music streaming backend.
All paths, settings, and constants are defined here.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Base Paths ──────────────────────────────────────────────────────────────
# Root of the backend package (backend/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Directory where downloaded songs are cached
SONGS_DIR = BASE_DIR / "songs"
SONGS_DIR.mkdir(parents=True, exist_ok=True)

# Directory for log files
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Database ────────────────────────────────────────────────────────────────
# Set DATABASE_URL in .env for Neon Postgres; falls back to local SQLite for dev
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR / 'music_cache.db'}")

# ── YouTube Search ──────────────────────────────────────────────────────────
MAX_SEARCH_RESULTS = 10

# ── yt-dlp ──────────────────────────────────────────────────────────────────
YTDLP_OPTIONS = {
    "format": "bestaudio/best",
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }
    ],
    "quiet": True,
    "no_warnings": True,
}

# ── Server ──────────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# ── Cache Management ────────────────────────────────────────────────────────
MAX_CACHE_SIZE_MB = int(os.getenv("MAX_CACHE_SIZE_MB", "500"))

# ── Redis ───────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Spotify ─────────────────────────────────────────────────────────────────
# dotenv is loaded at the top of this file
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# ── AI / Gemini ─────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
