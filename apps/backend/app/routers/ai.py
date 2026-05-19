"""AI module — Claude conversations (chat sidebar), voice, daily briefings."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.ai import Briefing
from app.schemas.food import BriefingRead
from app.services.briefings import (
    get_or_generate_today,
    get_today,
    mark_read,
)

router = APIRouter()


# ---------- Conversations (chat sidebar) — stubs ----------


@router.get("/conversations")
def list_conversations(db: Annotated[Session, Depends(get_db)]):
    return {"conversations": [], "todo": "List recent Conversation rows for household"}


@router.post("/conversations")
def create_conversation(db: Annotated[Session, Depends(get_db)]):
    return {"conversation": None, "todo": "Create Conversation, return id"}


@router.get("/conversations/{conv_id}/messages")
def list_messages(conv_id: str, db: Annotated[Session, Depends(get_db)]):
    return {"messages": [], "todo": "Return Message rows ordered by created_at"}


@router.post("/conversations/{conv_id}/messages")
def post_message(conv_id: str, db: Annotated[Session, Depends(get_db)]):
    return {"reply": None, "todo": "Wire to Claude with conversation history + tools"}


# ---------- Voice — stubs ----------


@router.post("/voice/session")
def start_voice_session(db: Annotated[Session, Depends(get_db)]):
    return {"session_id": None, "ws_url": None, "todo": "Wire to services.voice"}


@router.post("/voice/session/{session_id}/end")
def end_voice_session(session_id: str, db: Annotated[Session, Depends(get_db)]):
    return {"session_id": session_id, "todo": "Persist VoiceSession, transcript, duration"}


# ---------- Briefings (Sprint 7) ----------


@router.get("/briefings/today", response_model=BriefingRead)
def todays_briefing(
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> BriefingRead:
    """Return today's briefing, generating it on demand if missing."""
    briefing = get_or_generate_today(
        db, household=household, user_id=user.id, force=False
    )
    db.commit()
    return BriefingRead.model_validate(briefing)


@router.post("/briefings/generate", response_model=BriefingRead)
def regenerate_briefing(
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> BriefingRead:
    """Force a fresh briefing — soft-deletes the existing today and regenerates."""
    briefing = get_or_generate_today(
        db, household=household, user_id=user.id, force=True
    )
    db.commit()
    return BriefingRead.model_validate(briefing)


@router.post("/briefings/{briefing_id}/read", response_model=BriefingRead)
def mark_briefing_read(
    briefing_id: uuid.UUID,
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> BriefingRead:
    briefing = db.get(Briefing, briefing_id)
    if briefing is None or briefing.household_id != household.id:
        raise HTTPException(404, "briefing not found")
    mark_read(db, briefing)
    db.commit()
    return BriefingRead.model_validate(briefing)


# Re-exported for use by other modules
__all__ = ["router", "get_today"]
