"""
Lyrics API routes.
Fetches time-synced lyrics from LRCLIB (free, no API key).
"""

import re
from fastapi import APIRouter, Query, HTTPException
import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Lyrics"])

LRCLIB_API = "https://lrclib.net/api"


def _parse_lrc(lrc_text: str) -> list[dict]:
    """Parse LRC format into a list of {time, text} dicts."""
    lines = []
    for match in re.finditer(r"\[(\d{2}):(\d{2})\.(\d{2,3})\]\s*(.*)", lrc_text):
        mins, secs, ms_str, text = match.groups()
        # Normalize milliseconds (handle both 2 and 3 digit)
        ms = int(ms_str.ljust(3, "0"))
        time_sec = int(mins) * 60 + int(secs) + ms / 1000.0
        if text.strip():
            lines.append({"time": round(time_sec, 2), "text": text.strip()})
    return lines


@router.get("/lyrics")
async def get_lyrics(
    title: str = Query(..., description="Song title"),
    artist: str = Query("", description="Artist name"),
):
    """
    Fetch synced lyrics for a song.
    Returns time-synced lines if available, otherwise plain lyrics.
    """
    # Try synced search first
    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist

    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{LRCLIB_API}/search",
                params=params,
                headers={"User-Agent": "Auralux/2.0"},
                timeout=8.0,
            )

        if res.status_code != 200:
            logger.warning("LRCLIB search failed: %s", res.status_code)
            return {"synced": False, "lines": [], "plain": ""}

        results = res.json()
        if not results:
            return {"synced": False, "lines": [], "plain": ""}

        # Pick the best result (first one with synced lyrics)
        best = None
        plain_fallback = ""
        for item in results:
            if item.get("syncedLyrics"):
                best = item
                break
            if not plain_fallback and item.get("plainLyrics"):
                plain_fallback = item["plainLyrics"]

        if best and best.get("syncedLyrics"):
            lines = _parse_lrc(best["syncedLyrics"])
            logger.info("Found synced lyrics for '%s' (%d lines)", title, len(lines))
            return {
                "synced": True,
                "lines": lines,
                "plain": best.get("plainLyrics", ""),
            }

        # Return plain lyrics as fallback
        return {"synced": False, "lines": [], "plain": plain_fallback}

    except Exception as e:
        logger.error("Lyrics fetch error: %s", e)
        return {"synced": False, "lines": [], "plain": ""}
