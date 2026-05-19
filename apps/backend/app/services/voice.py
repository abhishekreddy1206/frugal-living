"""
Voice service — "hey Hearth" hands-free interaction while cooking.

Implementation plan:
  1. Frontend captures microphone audio in chunks via Web Audio API.
  2. Stream audio over WebSocket to /api/v1/ai/voice/session/{id}/ws.
  3. Backend uses OpenAI Whisper (or Claude voice when available) for STT.
  4. Transcript flows into a Claude conversation with scope='voice'.
  5. Claude response goes through TTS (ElevenLabs, OpenAI TTS, or Whisper TTS).
  6. Audio stream returned to client over the same WebSocket.

Design constraints:
  - Wake-word detection runs client-side (Picovoice Porcupine or similar) — we
    only stream audio after the wake phrase is detected, for privacy.
  - All transcripts persist to ai.voice_sessions for review and "things you've
    asked while cooking" history.
"""
from app.config import settings


def start_session(household_id: str, user_id: str) -> dict:
    """Stub. Create a VoiceSession and return session id + ws URL."""
    if not settings.openai_api_key:
        return {"status": "skipped", "reason": "OPENAI_API_KEY not configured for STT/TTS"}
    raise NotImplementedError("Implement voice session lifecycle")
