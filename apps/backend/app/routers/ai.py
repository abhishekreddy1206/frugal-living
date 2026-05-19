"""AI module — Claude conversations (chat sidebar), voice, daily briefings."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


# ---------- Conversations (chat sidebar) ----------

@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    return {"conversations": [], "todo": "List recent Conversation rows for household"}


@router.post("/conversations")
def create_conversation(db: Session = Depends(get_db)):
    return {"conversation": None, "todo": "Create Conversation, return id"}


@router.get("/conversations/{conv_id}/messages")
def list_messages(conv_id: str, db: Session = Depends(get_db)):
    return {"messages": [], "todo": "Return Message rows ordered by created_at"}


@router.post("/conversations/{conv_id}/messages")
def post_message(conv_id: str, db: Session = Depends(get_db)):
    """Send a user message, get an assistant response (streamed in production)."""
    return {"reply": None, "todo": "Wire to Claude with conversation history + tools"}


# ---------- Voice ----------

@router.post("/voice/session")
def start_voice_session(db: Session = Depends(get_db)):
    """Start a 'hey Hearth' voice session. Returns a session id + websocket URL."""
    return {"session_id": None, "ws_url": None, "todo": "Wire to services.voice"}


@router.post("/voice/session/{session_id}/end")
def end_voice_session(session_id: str, db: Session = Depends(get_db)):
    return {"session_id": session_id, "todo": "Persist VoiceSession, transcript, duration"}


# ---------- Briefings ----------

@router.get("/briefings/today")
def todays_briefing(db: Session = Depends(get_db)):
    return {"briefing": None, "todo": "Read Briefing for today; generate if missing"}


@router.post("/briefings/generate")
def generate_briefing(db: Session = Depends(get_db)):
    """Force-generate a briefing for the household (also runs as a scheduled job)."""
    return {"briefing": None, "todo": "Wire to services.llm.generate_briefing"}
