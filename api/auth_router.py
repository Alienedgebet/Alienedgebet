"""Authentication endpoints for real AlienEdge users.

The browser receives only an opaque HttpOnly session cookie.  User identity is
read from the server-side session on every protected request.
"""
from __future__ import annotations

import os
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
    create_session,
    create_user,
    get_user_for_session,
    revoke_session,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


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
