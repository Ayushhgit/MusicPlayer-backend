"""
Spotify Playlist Import Service.
Extracts tracks from Spotify via:
  1. Official Spotify API (requires Premium on dev account)
  2. Embed page scraping (no auth needed, works for public playlists)
Then searches YouTube for each track.
"""

import asyncio
import json
import re
from typing import Any

import httpx
import yt_dlp

from app.utils.logger import get_logger

logger = get_logger(__name__)

# yt-dlp options for YouTube search per track
_SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": True,
    "default_search": "ytsearch",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _is_spotify_url(url: str) -> bool:
    """Check if a URL is a valid Spotify playlist link."""
    return bool(re.match(r"https?://(open\.)?spotify\.com/(playlist|album)/\w+", url))


def _extract_playlist_id(url: str) -> str:
    """Extract the playlist/album ID from a Spotify URL."""
    match = re.search(r"(playlist|album)/([a-zA-Z0-9]+)", url)
    if not match:
        raise ValueError("Could not extract playlist ID from URL.")
    return match.group(2)


# ── Method 1: Official Spotify API (needs Premium) ─────────────────────────

async def _get_spotify_token(client_id: str, client_secret: str) -> str:
    """Fetch an ephemeral access token using Spotify Client Credentials Flow."""
    auth_url = "https://accounts.spotify.com/api/token"
    auth_data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(
            auth_url,
            data=auth_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        if res.status_code != 200:
            raise ValueError(f"Spotify auth failed ({res.status_code}): {res.text}")

        token = res.json().get("access_token")
        if not token:
            raise ValueError("Spotify API did not return an access token.")
        return token


async def _extract_via_api(url: str, token: str) -> dict[str, Any]:
    """Extract tracks from Spotify Web API (requires Premium)."""
    playlist_id = _extract_playlist_id(url)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers=headers,
            timeout=10.0,
        )
        if res.status_code != 200:
            raise ValueError(f"Spotify API Error: {res.status_code} - {res.text}")

        data = res.json()

    playlist_name = data.get("name", "Spotify Import")
    tracks = []

    for item in data.get("tracks", {}).get("items", []):
        track = item.get("track")
        if not track:
            continue

        title = track.get("name", "")
        artists = [a.get("name", "") for a in track.get("artists", [])]
        artist = ", ".join(artists)

        duration_ms = track.get("duration_ms", 0)
        mins, secs = divmod(duration_ms // 1000, 60)
        duration = f"{mins}:{secs:02d}"

        images = track.get("album", {}).get("images", [])
        thumbnail = images[-1]["url"] if images else ""

        tracks.append({
            "title": title,
            "artist": artist,
            "duration": duration,
            "thumbnail": thumbnail,
            "query": f"{artist} - {title}" if artist else title,
        })

    return {"playlist_name": playlist_name, "tracks": tracks}


# ── Method 2: Embed page scraping (no auth needed) ─────────────────────────

async def _extract_via_embed(url: str) -> dict[str, Any]:
    """
    Scrape the public Spotify embed page to extract track data.
    Works for any public playlist without API keys or Premium.
    """
    playlist_id = _extract_playlist_id(url)
    embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        res = await client.get(embed_url, headers=_HEADERS, timeout=15.0)
        if res.status_code != 200:
            raise ValueError(f"Embed page returned {res.status_code}")

    html = res.text

    # Try __NEXT_DATA__ JSON blob first
    next_match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if next_match:
        try:
            blob = json.loads(next_match.group(1))
            return _parse_next_data(blob)
        except Exception as e:
            logger.warning("Failed to parse __NEXT_DATA__: %s", e)

    # Fallback: extract track names from raw HTML patterns
    tracks = _parse_embed_html(html)
    if tracks:
        return {"playlist_name": "Spotify Import", "tracks": tracks}

    raise ValueError("Could not extract track data from embed page.")


def _parse_next_data(blob: dict) -> dict[str, Any]:
    """Parse the __NEXT_DATA__ JSON blob from the embed page."""
    # Navigate through the Next.js data structure
    props = blob.get("props", {}).get("pageProps", {})

    # The structure may vary; try common paths
    state = props.get("state", {})
    data = state.get("data", {}) if state else props

    # Try to find entity directly
    entity = data.get("entity", {})
    if not entity:
        # Try alternate path
        for key in data:
            if isinstance(data[key], dict) and "name" in data[key]:
                entity = data[key]
                break

    playlist_name = entity.get("name", "Spotify Import")

    # Extract tracks from the entity
    raw_tracks = []
    track_list = entity.get("trackList", [])
    if track_list:
        raw_tracks = track_list
    else:
        # Try items path
        items = entity.get("tracks", {}).get("items", []) if isinstance(entity.get("tracks"), dict) else []
        raw_tracks = items

    tracks = []
    for t in raw_tracks:
        # Handle different data shapes
        if isinstance(t, dict):
            title = t.get("title", t.get("name", ""))
            subtitle = t.get("subtitle", "")
            artist = subtitle if subtitle else t.get("artist", "")
            duration_ms = t.get("duration", 0)

            if isinstance(duration_ms, (int, float)) and duration_ms > 1000:
                mins, secs = divmod(int(duration_ms) // 1000, 60)
                duration = f"{mins}:{secs:02d}"
            else:
                duration = "0:00"

            tracks.append({
                "title": title,
                "artist": artist,
                "duration": duration,
                "thumbnail": "",
                "query": f"{artist} - {title}" if artist else title,
            })

    if not tracks:
        raise ValueError("No tracks found in __NEXT_DATA__")

    return {"playlist_name": playlist_name, "tracks": tracks}


def _parse_embed_html(html: str) -> list[dict[str, Any]]:
    """Fallback: extract track names from embed HTML using regex."""
    # Look for track title patterns in the HTML
    track_matches = re.findall(
        r'"name"\s*:\s*"([^"]+)"[^}]*?"artists"[^}]*?"name"\s*:\s*"([^"]+)"',
        html,
    )
    tracks = []
    seen = set()
    for title, artist in track_matches:
        key = f"{artist}-{title}"
        if key in seen:
            continue
        seen.add(key)
        tracks.append({
            "title": title,
            "artist": artist,
            "duration": "0:00",
            "thumbnail": "",
            "query": f"{artist} - {title}",
        })
    return tracks


# ── YouTube search ──────────────────────────────────────────────────────────

def _search_youtube_for_track(query: str) -> dict[str, Any] | None:
    """Search YouTube for a single track and return the top result."""
    search_query = f"ytsearch1:{query}"
    try:
        with yt_dlp.YoutubeDL(_SEARCH_OPTS) as ydl:
            info = ydl.extract_info(search_query, download=False)

        entries = info.get("entries", []) if info else []
        if not entries or not entries[0]:
            return None

        item = entries[0]
        duration_raw = item.get("duration")
        if isinstance(duration_raw, (int, float)) and duration_raw:
            mins, secs = divmod(int(duration_raw), 60)
            duration = f"{mins}:{secs:02d}"
        else:
            duration = str(duration_raw) if duration_raw else "N/A"

        thumbnails = item.get("thumbnails", [])
        thumbnail = thumbnails[-1]["url"] if thumbnails else (
            f"https://i.ytimg.com/vi/{item.get('id', '')}/hqdefault.jpg"
        )

        return {
            "title": item.get("title", "Unknown"),
            "video_id": item.get("id", item.get("url", "")),
            "thumbnail": thumbnail,
            "channel": item.get("channel", item.get("uploader", "Unknown")),
            "duration": duration,
        }
    except Exception as e:
        logger.warning("YouTube search failed for '%s': %s", query, e)
        return None


# ── Main entry point ────────────────────────────────────────────────────────

async def import_spotify_playlist(
    url: str, client_id: str = "", client_secret: str = ""
) -> dict[str, Any]:
    """
    Import a Spotify playlist:
    1. Try Spotify API (needs Premium dev account)
    2. Fallback: scrape Spotify embed page (no auth)
    3. Search YouTube for each extracted track
    """
    if not _is_spotify_url(url):
        raise ValueError("Invalid Spotify playlist URL")

    loop = asyncio.get_event_loop()
    spotify_tracks: list[dict[str, Any]] = []
    playlist_name = "Spotify Import"

    # ── Attempt 1: Official API ──────────────────────────────────────────
    if client_id and client_secret:
        logger.info("Attempting Spotify API extraction...")
        try:
            token = await _get_spotify_token(client_id, client_secret)
            api_data = await _extract_via_api(url, token)
            spotify_tracks = api_data["tracks"]
            playlist_name = api_data["playlist_name"]
            logger.info("API: fetched %d tracks from '%s'", len(spotify_tracks), playlist_name)
        except Exception as e:
            logger.warning("Spotify API failed: %s", e)

    # ── Attempt 2: Embed page scraping ───────────────────────────────────
    if not spotify_tracks:
        logger.info("Attempting embed page scraping...")
        try:
            embed_data = await _extract_via_embed(url)
            spotify_tracks = embed_data["tracks"]
            playlist_name = embed_data.get("playlist_name", playlist_name)
            logger.info("Embed: fetched %d tracks from '%s'", len(spotify_tracks), playlist_name)
        except Exception as e:
            logger.warning("Embed scraping failed: %s", e)

    if not spotify_tracks:
        raise ValueError(
            "Could not extract tracks from Spotify. "
            "The playlist might be private or the service is temporarily unavailable."
        )

    # ── Step 2: Search YouTube for each track ────────────────────────────
    logger.info("Searching YouTube for %d tracks...", len(spotify_tracks))
    matched_songs = []

    for track in spotify_tracks:
        try:
            result = await loop.run_in_executor(
                None, _search_youtube_for_track, track["query"]
            )
            if result:
                matched_songs.append(result)
        except Exception as e:
            logger.warning("Failed to match '%s': %s", track["query"], e)
            continue

    logger.info(
        "Matched %d/%d tracks from '%s'",
        len(matched_songs), len(spotify_tracks), playlist_name,
    )

    return {
        "playlist_name": playlist_name,
        "total_tracks": len(spotify_tracks),
        "matched_tracks": len(matched_songs),
        "songs": matched_songs,
    }
