"""
Event emitter — the single point through which all tier-spanning activity flows.

Per CLAUDE.md rule #5: every meaningful mutation writes a row to `core.events`.
Streaks, undo, analytics, and the future community feed all read from one table.

Event type convention: `<tier>.<entity>.<action>` (lowercase, singular entity,
past-tense verb). Document new types in ARCHITECTURE.md §5.5.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.core import Event

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def emit_event(
    db: Session,
    *,
    event_type: str,
    household_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> Event:
    """Write a row to core.events. Caller is responsible for the surrounding transaction."""
    if not _EVENT_TYPE_RE.match(event_type):
        raise ValueError(
            f"event_type {event_type!r} must match <tier>.<entity>.<action>"
        )

    event = Event(
        household_id=household_id,
        user_id=user_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
    )
    db.add(event)
    db.flush()
    return event
