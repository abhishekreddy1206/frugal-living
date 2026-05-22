"""AI module — Claude conversations (chat sidebar), voice, daily briefings."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import asc
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.ai import Briefing, Conversation, Message
from app.schemas.ai import (
    ChatMessageRequest,
    ChatTurnResponse,
    ConversationOpenRequest,
    ConversationOpenResponse,
    MessageRead,
)
from app.schemas.food import BriefingRead
from app.services.briefings import (
    get_or_generate_today,
    get_today,
    mark_read,
)
from app.services.chat import get_or_create_conversation, run_chat_turn

router = APIRouter()


# ---------- Conversations (chat sidebar) ----------


@router.post("/conversations", response_model=ConversationOpenResponse)
def open_conversation(
    request: ConversationOpenRequest,
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> ConversationOpenResponse:
    """Get-or-create the conversation for a page and return its message history."""
    conv = get_or_create_conversation(db, household=household, page=request.page)
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(asc(Message.created_at))
        .all()
    )
    db.commit()
    return ConversationOpenResponse(
        conversation_id=conv.id,
        page=conv.metadata_.get("page", "general"),
        messages=[MessageRead.model_validate(m) for m in messages],
    )


@router.post("/conversations/{conv_id}/messages", response_model=ChatTurnResponse)
def post_message(
    conv_id: uuid.UUID,
    request: ChatMessageRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ChatTurnResponse:
    """Run one chat turn: persist the message, call the assistant, execute actions."""
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.household_id != household.id or conv.deleted_at is not None:
        raise HTTPException(404, "conversation not found")
    response = run_chat_turn(
        db, household=household, user=user, conversation=conv, content=request.content
    )
    db.commit()
    return response


@router.get("/conversations")
def list_conversations(db: Annotated[Session, Depends(get_db)]):
    """Conversation-list view. Stub — no thread-list UI in v1."""
    return {"conversations": [], "todo": "List recent Conversation rows for household"}


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
