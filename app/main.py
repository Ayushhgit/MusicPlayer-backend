"""
FastAPI main application entry point.
Sets up CORS, routers, database initialization, and static file serving.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.search_routes import router as search_router
from app.api.stream_routes import router as stream_router
from app.api.playlist_routes import router as playlist_router
from app.api.custom_playlist_routes import router as custom_playlist_router
from app.api.history_routes import router as history_router
from app.api.lyrics_routes import router as lyrics_router
from app.api.ai_routes import router as ai_router
from app.database.db import init_db
from app.services.redis_service import init_redis, close_redis
from app.utils.config import SONGS_DIR
from app.utils.logger import get_logger

logger = get_logger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize DB and Redis on startup."""
    logger.info("Initializing database and Redis...")
    await init_db()
    await init_redis()
    logger.info("Database and Redis initialized. Server is ready.")
    yield
    logger.info("Server shutting down.")
    await close_redis()


app = FastAPI(
    title="Auralux Streaming API",
    description="A full-featured music streaming backend powered by YouTube, Redis, and Postgres.",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static Files ────────────────────────────────────────────────────────────
app.mount("/local", StaticFiles(directory=str(SONGS_DIR)), name="local_songs")

# ── Routers ─────────────────────────────────────────────────────────────────
app.include_router(search_router)
app.include_router(stream_router)
app.include_router(playlist_router)
app.include_router(custom_playlist_router)
app.include_router(history_router)
app.include_router(lyrics_router)
app.include_router(ai_router)


# ── Frontend ────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/style.css", include_in_schema=False)
async def serve_css():
    return FileResponse(str(FRONTEND_DIR / "style.css"), media_type="text/css")


@app.get("/script.js", include_in_schema=False)
async def serve_js():
    return FileResponse(str(FRONTEND_DIR / "script.js"), media_type="application/javascript")
