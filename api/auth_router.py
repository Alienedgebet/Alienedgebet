"""Authentication endpoints for real AlienEdge users.

The browser receives only an opaque HttpOnly session cookie.  User identity is
read from the server-side session on every protected request.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.auth_store import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    AuthError,
    EmailAlreadyRegistered,
    InvalidCredentials,
    authenticate,
    check_rate_limit,
    _normalize_email,
    consume_password_reset,
    create_password_reset,
    create_session,
    create_user,
    get_user_for_session,
    revoke_session,
    set_password,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    password: str = Field(min_length=12, max_length=256)


def _client_key(request: Request) -> str:
    # The reverse proxy supplies X-Real-IP. Only trust it when this service is
    # behind the local proxy; direct clients still get a bounded bucket.
    forwarded = request.headers.get("x-real-ip")
    if request.client and request.client.host in {"127.0.0.1", "::1"} and forwarded:
        return forwarded[:64]
    return request.client.host if request.client else "unknown"


def _rate(request: Request, bucket: str, limit: int) -> None:
    if not check_rate_limit(f"{bucket}:{_client_key(request)}", limit, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


def _secure_cookie() -> bool:
    configured = os.getenv("SESSION_COOKIE_SECURE")
    if configured is not None:
        return configured.lower() not in {"0", "false", "no"}
    return os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower() == "production"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )


def current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


CurrentUser = Annotated[dict, Depends(current_user)]


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, request: Request, response: Response) -> dict:
    _rate(request, "signup", 8)
    try:
        user = create_user(payload.email, payload.password)
    except EmailAlreadyRegistered:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    except ValueError:
        raise HTTPException(status_code=422, detail="Enter a valid email and a password of at least 12 characters.")
    token = create_session(user["user_id"])
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    _rate(request, "login", 12)
    try:
        user = authenticate(payload.email, payload.password)
    except InvalidCredentials:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_session(user["user_id"])
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    revoke_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"user": user}


# ── PASSWORD RESET (2026-10-12) ────────────────────────────────────────────
# Delivery is pluggable. When SMTP_HOST/SMTP_USER/SMTP_PASS are set in the
# environment the link is emailed automatically. Until then the link is
# written to a root-only log (output/auth_reset_links.log, chmod 600) and
# forwarded to the user through the support channel — an honest, working
# flow for a small user base instead of a dead "check your email" button.
RESET_LINK_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "auth_reset_links.log")


def _deliver_reset_link(email: str, token: str) -> None:
    base = os.getenv("APP_BASE_URL", "https://www.alienedge.tech")
    link = f"{base}/reset-password?token={token}"
    host, port = os.getenv("SMTP_HOST"), os.getenv("SMTP_PORT")
    user, pw, frm = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"), os.getenv("SMTP_FROM")
    if host and user and pw:
        try:
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["Subject"] = "AlienEdge — reset your password"
            msg["From"] = frm or user
            msg["To"] = email
            msg.set_content(chr(10).join([
                "Someone requested a password reset for your AlienEdge account.",
                "",
                f"Reset it here (link valid for 1 hour): {link}",
                "",
                "If you did not request this, ignore this email — nothing changes.",
            ]))

            with smtplib.SMTP(host, int(port or 587), timeout=20) as smtp:
                smtp.starttls()
                smtp.login(user, pw)
                smtp.send_message(msg)
            print(f"[auth] reset link emailed to {email}")
            return
        except Exception as exc:
            print(f"[auth][WARN] reset email failed, falling back to ops log: {exc}")
    # Ops-assisted delivery path.
    try:
        with open(RESET_LINK_LOG, "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} email={email} link={link}\n")
        os.chmod(RESET_LINK_LOG, 0o600)
        print(f"[auth] reset link logged for ops delivery to {email}")
    except Exception as exc:
        print(f"[auth][ERROR] could not log reset link: {exc}")


@router.post("/forgot-password", status_code=202)
def forgot_password(payload: ForgotPasswordRequest, request: Request) -> dict:
    _rate(request, "forgot-password", 3)
    token = create_password_reset(payload.email)
    if token:
        _deliver_reset_link(_normalize_email(payload.email), token)
    # ALWAYS the same 202 response — the endpoint must never reveal whether
    # an email has an account.
    return {"detail": "If an account exists for that email, a reset link is on its way."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request) -> dict:
    _rate(request, "reset-password", 10)
    if len(payload.password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters.")
    user_id = consume_password_reset(payload.token)
    if user_id is None:
        raise HTTPException(status_code=400,
                            detail="This reset link is invalid or has expired. Request a new one.")
    set_password(user_id, payload.password)
    return {"detail": "Password updated. All other devices were logged out — log in with your new password."}
