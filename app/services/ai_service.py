"""
AI Service wrapper.
Uses Gemini API to generate smart autoplay recommendations and DJ transitions.
"""

import json
from io import BytesIO

from google import genai
from gtts import gTTS

from app.utils.config import GEMINI_API_KEY
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Initialize client using the API key from config
try:
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here" else None
except Exception as e:
    logger.error("Failed to initialize Gemini Client: %s", e)
    client = None


def is_ai_enabled() -> bool:
    return client is not None


def generate_autoplay_recommendations(recent_songs: list[dict]) -> list[str]:
    """
    Given a list of recently played song dictionaries, use Gemini to recommend
    5 new songs that match the vibe and continue the listening journey.
    Returns a list of search queries (e.g., ["Artist - Title"]).
    """
    if not is_ai_enabled():
        logger.warning("Gemini API not configured. Returning empty recommendations.")
        return []

    # Format the recent history for the prompt
    history_text = "\n".join(
        [f"- {s.get('title')} by {s.get('channel')}" for s in recent_songs]
    )

    prompt = f"""
    You are an expert music curator and DJ. The user has recently listened to the following songs:
    {history_text}

    Based on the exact vibe, genre, and tempo of these tracks, recommend 5 new songs that would perfectly follow next in a queue. 
    Do NOT recommend any of the songs already in the list above.

    Return your response strictly as a raw JSON array of strings, where each string is formatted as "Artist - Title". 
    Do not include markdown formatting or any other text.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        # Clean up possible markdown fences
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        recommendations = json.loads(raw_text.strip())
        if not isinstance(recommendations, list):
            raise ValueError("Gemini did not return a list.")

        logger.info("Generated %d recommendations from Gemini.", len(recommendations))
        return recommendations[:5]

    except Exception as e:
        logger.error("Failed to generate autoplay recommendations: %s", e)
        return []


def generate_dj_transition_audio(previous_song: dict | None, next_song: dict) -> BytesIO:
    """
    Use Gemini to write a smooth, late-night radio DJ transition script connecting 
    the previous song to the next song, then use gTTS to generate an MP3 audio stream of it.
    """
    script = f"Up next, {next_song.get('title', 'a great track')}."

    if is_ai_enabled():
        prompt = "Act as a smooth, charismatic late-night radio DJ."
        if previous_song:
            prompt += f"\nWe just listened to '{previous_song.get('title')}' by {previous_song.get('channel', 'Unknown')}."
        prompt += f"\nNow we are transitioning into '{next_song.get('title')}' by {next_song.get('channel', 'Unknown')}."
        prompt += "\nWrite exactly 2 sentences of commentary connecting the vibe of the last song to the next one, ending by introducing the next song. Do not use sound effects or bracketed stage directions like [Chuckle]. Just the spoken words."

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            script = response.text.strip()
            logger.info("Generated DJ script: %s", script)
        except Exception as e:
            logger.error("Failed to generate DJ script, using fallback. Error: %s", e)
    else:
        logger.warning("Gemini API not configured. Using fallback DJ script.")

    # Convert text to speech using gTTS
    try:
        tts = gTTS(text=script, lang="en", tld="us", slow=False)
        audio_stream = BytesIO()
        tts.write_to_fp(audio_stream)
        audio_stream.seek(0)
        return audio_stream
    except Exception as e:
        logger.error("gTTS failed: %s", e)
        raise ValueError("Failed to generate TTS audio.")
