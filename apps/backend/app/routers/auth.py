"""Auth endpoints: signup, login, logout, me, password, multi-household, invites."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.core import (
    AuditLog,
    Household,
    HouseholdMember,
    Subscription,
    User,
)
from app.schemas.auth import (
    HouseholdRead,
    SignupRequest,
    SignupResponse,
    UserRead,
)
from app.services.auth import sessions as session_svc
from app.services.auth.passwords import hash_password

router = APIRouter()


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return ua, ip


def _audit(db: Session, *, action: str, user_id, payload: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=user_id,
        action=action,
        target_type="user",
        target_id=user_id,
        payload=payload or {},
    ))


@router.post("/signup", response_model=SignupResponse)
def signup(
    request: SignupRequest,
    response: Response,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SignupResponse:
    """Create a new user + household + owner membership + free subscription; open a session."""
    user = User(
        email=str(request.email).lower(),
        hashed_password=hash_password(request.password),
        display_name=request.display_name,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already in use") from None

    household = Household(name=request.household_name)
    db.add(household)
    db.flush()

    db.add(HouseholdMember(user_id=user.id, household_id=household.id, role="owner"))
    db.add(Subscription(
        user_id=user.id, plan="free", status="active",
        tier_a_enabled=True, tier_b_enabled=True, tier_s_enabled=False,
    ))
    db.flush()

    ua, ip = _request_meta(http_request)
    sess, raw_token = session_svc.create_session(
        db, user=user, active_household_id=household.id, user_agent=ua, ip=ip,
    )
    _audit(db, action="auth.signup", user_id=user.id, payload={"email": user.email})
    db.commit()

    session_svc.set_session_cookie(response, raw_token)
    return SignupResponse(
        user=UserRead.model_validate(user),
        household=HouseholdRead.model_validate(household),
    )
