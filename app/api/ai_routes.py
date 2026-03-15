"""
AI Routes.
Endpoints for Autoplay recommendations and DJ transitions.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.ai_service import generate_autoplay_recommendations, generate_dj_transition_audio, is_ai_enabled
from app.services.youtube_service import search_videos
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Features"])


class AutoplayRequest(BaseModel):
    recent_songs: list[dict]
    # Expects a list of dicts with 'title' and 'channel'


class DJTransitionRequest(BaseModel):
    previous_song: dict | None
    next_song: dict
    # Expects dicts with 'title' and 'channel'


@router.get("/status")
async def get_ai_status():
    """Check if the Gemini DJ/Autoplay AI is enabled on the backend."""
    return {"enabled": is_ai_enabled()}


@router.post("/autoplay")
async def autoplay(request: AutoplayRequest):
    """
    Generate 5 new contextual tracks to keep the playlist going.
    Queries Gemini for track recommendations, then automatically
    searches YouTube for those queries to resolve them into real tracks.
    """
    if not is_ai_enabled():
        raise HTTPException(status_code=503, detail="AI is not configured (missing Gemini API Key).")

    try:
        # 1. Ask Gemini for 5 song queries based on history
        logger.info("Requesting autoplay recommendations for history of length %d", len(request.recent_songs))
        queries = generate_autoplay_recommendations(request.recent_songs)
        
        if not queries:
            return {"recommended_tracks": []}

        # 2. Map queries to real YouTube videos
        # We perform a generic search for each query and take the first hit.
        resolved_tracks = []
        for q in queries:
            try:
                search_results = await search_videos(q)
                if isinstance(search_results, list) and len(search_results) > 0:
                    resolved_tracks.append(search_results[0])
            except Exception as e:
                logger.warning("Failed to resolve autoplay query '%s': %s", q, e)
                continue

        return {"recommended_tracks": resolved_tracks}

    except Exception as exc:
        logger.error("Autoplay generation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate autoplay queue.")


@router.post("/dj-transition")
async def dj_transition(request: DJTransitionRequest):
    """
    Generate a TTS audio stream of an AI DJ transitioning between two songs.
    Returns the raw MP3 byte stream.
    """
    if not is_ai_enabled():
        raise HTTPException(status_code=503, detail="AI is not configured (missing Gemini API Key).")

    try:
        audio_stream = generate_dj_transition_audio(
            previous_song=request.previous_song,
            next_song=request.next_song
        )
        # Return as streaming MP3
        return StreamingResponse(audio_stream, media_type="audio/mpeg")
    except Exception as exc:
        logger.error("DJ transition error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate DJ transition audio.")
