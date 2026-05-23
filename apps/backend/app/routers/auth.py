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
    HouseholdInvite,
    HouseholdMember,
    Subscription,
    User,
)
from app.schemas.auth import (
    CreateHouseholdRequest,
    CreateInviteRequest,
    CreateInviteResponse,
    HouseholdRead,
    InvitePreview,
    LoginRequest,
    LoginResponse,
    MembershipRead,
    MeResponse,
    PasswordChangeRequest,
    SignupRequest,
    SignupResponse,
    SwitchHouseholdRequest,
    UserRead,
)
from app.services.auth import invites as invite_svc
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
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
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


@router.post("/households", response_model=HouseholdRead)
def create_household(
    request: CreateHouseholdRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> HouseholdRead:
    """Create a new household; the caller becomes its owner."""
    household = Household(name=request.name)
    db.add(household)
    db.flush()
    db.add(HouseholdMember(user_id=user.id, household_id=household.id, role="owner"))
    _audit(
        db,
        action="auth.household_created",
        user_id=user.id,
        payload={"household_id": str(household.id)},
    )
    db.commit()
    db.refresh(household)
    return HouseholdRead.model_validate(household)


@router.post("/switch-household", response_model=HouseholdRead)
def switch_household(
    request: SwitchHouseholdRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> HouseholdRead:
    """Set the current session's active household. 403 if the user isn't a member."""
    membership = (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == request.household_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="not a member of that household")

    sess = get_session_by_raw_token(db, session_token) if session_token else None
    if sess is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    sess.active_household_id = request.household_id
    db.flush()
    _audit(
        db,
        action="auth.household_switched",
        user_id=user.id,
        payload={"household_id": str(request.household_id)},
    )
    db.commit()
    household = db.get(Household, request.household_id)
    assert household is not None
    return HouseholdRead.model_validate(household)


def _require_owner(db: Session, *, user: User, household_id) -> None:
    membership = (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == household_id,
        )
        .one_or_none()
    )
    if membership is None or membership.role != "owner":
        raise HTTPException(status_code=403, detail="must be a household owner")


@router.post(
    "/households/{household_id}/invites",
    response_model=CreateInviteResponse,
)
def create_invite_endpoint(
    household_id,
    request: CreateInviteRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CreateInviteResponse:
    """Owner-only. Mint an invite; returns the raw token and a shareable URL (one-time)."""
    _require_owner(db, user=user, household_id=household_id)
    inv, raw = invite_svc.create_invite(
        db, household_id=household_id, role=request.role,
        created_by_user_id=user.id, email=request.email,
    )
    _audit(db, action="auth.invite_created", user_id=user.id,
           payload={"household_id": str(household_id), "invite_id": str(inv.id)})
    db.commit()
    return CreateInviteResponse(
        token=raw,
        url=f"/invite/{raw}",
        expires_at=inv.expires_at,
    )


@router.delete("/households/{household_id}/invites/{invite_id}")
def revoke_invite_endpoint(
    household_id,
    invite_id,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    """Owner-only. Revoke an unaccepted invite."""
    _require_owner(db, user=user, household_id=household_id)
    inv = db.get(HouseholdInvite, invite_id)
    if inv is None or str(inv.household_id) != str(household_id):
        raise HTTPException(status_code=404, detail="invite not found")
    invite_svc.revoke_invite(db, inv)
    _audit(db, action="auth.invite_revoked", user_id=user.id,
           payload={"invite_id": str(inv.id)})
    db.commit()
    return {"status": "revoked"}


@router.get("/invites/{token}", response_model=InvitePreview)
def preview_invite(
    token: str,
    db: Annotated[Session, Depends(get_db)],
    _user: CurrentUser,  # auth required to preview (keeps things simple)
) -> InvitePreview:
    """Preview an invite. 410 if not redeemable, 404 if no such token."""
    inv = invite_svc.get_invite_by_raw_token(db, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="invite not found")
    if not invite_svc.is_redeemable(inv):
        raise HTTPException(status_code=410, detail="invite is no longer redeemable")
    household = db.get(Household, inv.household_id)
    inviter = db.get(User, inv.created_by_user_id)
    return InvitePreview(
        household_name=household.name if household else "",
        role=inv.role,
        inviter_name=inviter.display_name if inviter else None,
        expires_at=inv.expires_at,
    )


@router.post("/invites/{token}/accept", response_model=HouseholdRead)
def accept_invite_endpoint(
    token: str,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> HouseholdRead:
    """Accept an invite — become a HouseholdMember with the invite's role. 410 if not redeemable."""
    inv = invite_svc.get_invite_by_raw_token(db, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="invite not found")
    if not invite_svc.is_redeemable(inv):
        raise HTTPException(status_code=410, detail="invite is no longer redeemable")
    invite_svc.accept_invite(db, inv=inv, user=user)
    household = db.get(Household, inv.household_id)
    _audit(db, action="auth.invite_accepted", user_id=user.id,
           payload={"invite_id": str(inv.id)})
    db.commit()
    assert household is not None
    return HouseholdRead.model_validate(household)
