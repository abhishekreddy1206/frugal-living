"""Auth endpoints: signup, login, logout, me, password, multi-household, invites."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.config import settings
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
    LoginRequest,
    LoginResponse,
    MembershipRead,
    MeResponse,
    PasswordChangeRequest,
    SignupRequest,
    SignupResponse,
    UserRead,
)
from app.services.auth import sessions as session_svc
from app.services.auth import throttle as throttle_svc
from app.services.auth.passwords import hash_password, verify_password
from app.services.auth.sessions import (
    clear_session_cookie,
    get_session_by_raw_token,
    revoke_other_sessions,
    revoke_session,
)

router = APIRouter()


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return ua, ip


def _audit(db: Session, *, action: str, user_id, payload: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor_user_id=user_id,
            action=action,
            target_type="user",
            target_id=user_id,
            payload=payload or {},
        )
    )


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
    db.add(
        Subscription(
            user_id=user.id,
            plan="free",
            status="active",
            tier_a_enabled=True,
            tier_b_enabled=True,
            tier_s_enabled=False,
        )
    )
    db.flush()

    ua, ip = _request_meta(http_request)
    sess, raw_token = session_svc.create_session(
        db,
        user=user,
        active_household_id=household.id,
        user_agent=ua,
        ip=ip,
    )
    _audit(db, action="auth.signup", user_id=user.id, payload={"email": user.email})
    db.commit()

    session_svc.set_session_cookie(response, raw_token)
    return SignupResponse(
        user=UserRead.model_validate(user),
        household=HouseholdRead.model_validate(household),
    )


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    """Verify credentials, open a session, set the cookie. 401 / 429 on failure."""
    user = db.query(User).filter(User.email == str(request.email).lower()).one_or_none()
    if user is None:
        # Same status as wrong-password to avoid email enumeration.
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="invalid email or password")

    locked, until = throttle_svc.is_locked(user)
    if locked:
        raise HTTPException(
            status_code=429,
            detail=f"account locked until {until.isoformat()}",
        )

    if user.hashed_password is None or not verify_password(request.password, user.hashed_password):
        throttle_svc.register_failed_login(db, user)
        db.commit()
        raise HTTPException(status_code=401, detail="invalid email or password")

    throttle_svc.reset_throttle(db, user)

    # Default the new session's active household to the user's first membership.
    membership = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.user_id == user.id)
        .order_by(HouseholdMember.created_at)
        .first()
    )
    active_household_id = membership.household_id if membership else None

    ua, ip = _request_meta(http_request)
    sess, raw_token = session_svc.create_session(
        db,
        user=user,
        active_household_id=active_household_id,
        user_agent=ua,
        ip=ip,
    )
    _audit(db, action="auth.login", user_id=user.id, payload={"email": user.email})
    db.commit()

    session_svc.set_session_cookie(response, raw_token)
    household = db.get(Household, active_household_id) if active_household_id else None
    if household is None:
        raise HTTPException(status_code=400, detail="user has no household")
    return LoginResponse(
        user=UserRead.model_validate(user),
        active_household=HouseholdRead.model_validate(household),
    )


@router.post("/logout")
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict:
    """Revoke the current session and clear the cookie."""
    if session_token:
        sess = get_session_by_raw_token(db, session_token)
        if sess is not None:
            revoke_session(db, sess)
    _audit(db, action="auth.logout", user_id=user.id)
    db.commit()
    clear_session_cookie(response)
    return {"status": "logged_out"}


@router.get("/me", response_model=MeResponse)
def me(
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    household: CurrentHousehold,
) -> MeResponse:
    """Return the current user, their household memberships, and the active household."""
    memberships = db.query(HouseholdMember).filter(HouseholdMember.user_id == user.id).all()
    member_reads = []
    for m in memberships:
        h = db.get(Household, m.household_id)
        if h is None:
            continue
        member_reads.append(
            MembershipRead(
                household=HouseholdRead.model_validate(h),
                role=m.role,
            )
        )
    return MeResponse(
        user=UserRead.model_validate(user),
        memberships=member_reads,
        active_household=HouseholdRead.model_validate(household),
    )


@router.post("/password")
def change_password(
    request: PasswordChangeRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    session_token: Annotated[
        str | None, Cookie(alias=settings.session_cookie_name)
    ] = None,
) -> dict:
    """Change password. Verifies the current one and revokes all *other* sessions."""
    if user.hashed_password is None or not verify_password(
        request.current_password, user.hashed_password
    ):
        raise HTTPException(status_code=401, detail="current password is wrong")
    user.hashed_password = hash_password(request.new_password)

    current_session = get_session_by_raw_token(db, session_token) if session_token else None
    revoke_other_sessions(db, user=user, except_session=current_session)
    _audit(db, action="auth.password_change", user_id=user.id)
    db.commit()
    return {"status": "password_changed"}
