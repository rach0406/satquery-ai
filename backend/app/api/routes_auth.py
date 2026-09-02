"""Authentication endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import (DEMO_PASSWORD, DEMO_USERNAME, AuthError, StorageError, get_store,
                    issue_token, username_problem, verify_token)
from ..config import settings

log = logging.getLogger("satquery.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
#: Field limits are deliberately permissive here and the *real* rules live in
#: :mod:`app.auth`. Pydantic rejects a short password with a 422 whose detail
#: is a list of objects, which a browser client cannot show to a person;
#: letting the request through means every credential problem comes back as a
#: 400 with one plain sentence the form can print as-is.
class SignupRequest(BaseModel):
    username: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=256)
    display_name: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    organisation: str | None = Field(default=None, max_length=96)


class LoginRequest(BaseModel):
    #: Accepts a username or an email address.
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)


class SessionResponse(BaseModel):
    token: str
    expires_at: int
    user: dict
    token_type: str = "bearer"


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------
def current_user(authorization: str | None = Header(default=None)) -> dict | None:
    """Resolve the bearer token to a user, or None when unauthenticated.

    Never raises for an absent header - see :func:`require_user` for the
    enforcing variant.
    """
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        username = verify_token(token.strip())
    except AuthError:
        return None
    user = get_store().get(username)
    return user.public() if user else None


def require_user(user: dict | None = Depends(current_user)) -> dict:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to use this endpoint.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def optional_user(user: dict | None = Depends(current_user)) -> dict | None:
    """Enforce a session only when the deployment asks for it."""
    if settings.require_auth and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This deployment requires authentication. Sign in first.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@router.get("/config")
def auth_config() -> dict:
    """What the client needs to know before showing a sign-in form."""
    store = get_store()
    return {
        "require_auth": settings.require_auth,
        "session_ttl_seconds": settings.session_ttl_seconds,
        "signup_enabled": True,
        "accounts": store.count(),
        "demo_account": (
            {"username": DEMO_USERNAME, "password": DEMO_PASSWORD}
            if settings.seed_demo_user and store.exists(DEMO_USERNAME) else None
        ),
        "password_policy": "At least 8 characters, including a letter and a number.",
        "note": (
            "Passwords are stored as PBKDF2-HMAC-SHA256 derivations (200,000 iterations, "
            "per-account salt). Sessions are HMAC-SHA256 signed tokens with an expiry. "
            "The account store is a local JSON file - single-node demo scope."
        ),
    }


@router.post("/check-username", tags=["auth"])
def check_username(payload: dict) -> dict:
    """Is this username usable? Lets the sign-up form answer before submitting."""
    name = str(payload.get("username", "")).strip()
    problem = username_problem(name)
    if problem:
        return {"available": False, "reason": problem}
    if get_store().exists(name):
        return {"available": False,
                "reason": f"The username '{name}' is already taken."}
    return {"available": True, "reason": None}


@router.post("/signup", response_model=SessionResponse,
             status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest) -> SessionResponse:
    """Register a new account. Open to anyone - there is no allow-list."""
    try:
        user = get_store().create(
            username=req.username, password=req.password,
            display_name=req.display_name, email=req.email,
            organisation=req.organisation,
        )
    except StorageError as exc:
        # The credentials were fine; the server could not persist them.
        log.error("signup storage failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # never surface a bare 500 on a sign-up form
        log.exception("unexpected signup failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Account creation failed unexpectedly ({type(exc).__name__}). "
                   "Please try again.") from exc
    token, exp = issue_token(user.username)
    return SessionResponse(token=token, expires_at=exp, user=user.public())


@router.post("/login", response_model=SessionResponse)
def login(req: LoginRequest) -> SessionResponse:
    """Sign in with a username or an email address."""
    if not req.username.strip() or not req.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter both your username (or email) and your password.")
    try:
        user = get_store().authenticate(req.username, req.password)
    except StorageError as exc:
        log.error("login storage failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except Exception as exc:
        log.exception("unexpected login failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sign-in failed unexpectedly ({type(exc).__name__}). "
                   "Please try again.") from exc
    token, exp = issue_token(user.username)
    return SessionResponse(token=token, expires_at=exp, user=user.public())


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    return {"user": user, "authenticated": True}


@router.post("/logout")
def logout(user: dict | None = Depends(current_user)) -> dict:
    """Sessions are stateless, so the client simply discards the token."""
    return {
        "ok": True,
        "signed_out": bool(user),
        "note": "Tokens are stateless and signed; discard it client-side. It expires on its own.",
    }
