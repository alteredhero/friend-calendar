"""The shared-password gate: reading the credential, signing the session cookie, the login routes."""
import hashlib
import hmac
import json
import logging
import os
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from passwords import ALGORITHM, verify_password
from paths import data_path
from web import NO_CACHE, STATIC_DIR

AUTH_PATH = data_path("auth.json")
SECRET_PATH = data_path(".session_secret")
AUTH_COOKIE = "fc_auth"

log = logging.getLogger("friend-calendar")
router = APIRouter()


def load_credential() -> str:
    """The stored credential from auth.json (empty string = gate disabled).

    Normally a hash written by set_password.py ("password_hash"); a plaintext "password"
    is still honoured so older setups keep working."""
    try:
        with open(AUTH_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    return (data.get("password_hash") or data.get("password") or "").strip()


def _password_matches(candidate: str, credential: str) -> bool:
    if credential.startswith(ALGORITHM + "$"):
        return verify_password(candidate, credential)
    return hmac.compare_digest(candidate.encode(), credential.encode())


def warn_if_open() -> None:
    if not load_credential():
        log.warning("NO GROUP PASSWORD SET - anyone who can reach this server can edit the "
                    "calendar. Run:  python set_password.py")


def _secret() -> str:
    """Persistent random key used to sign the auth cookie (so restarts don't log everyone out)."""
    if not os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "w") as f:
            f.write(secrets.token_hex(32))
    with open(SECRET_PATH) as f:
        return f.read().strip()


def _expected_token() -> str:
    return hmac.new(_secret().encode(), load_credential().encode(), hashlib.sha256).hexdigest()


# paths reachable without a session (login page + its assets + the login call)
_OPEN_PATHS = {"/login", "/api/login", "/favicon.ico"}


async def auth_gate(request: Request, call_next):
    if not load_credential():             # gate disabled: wide open
        return await call_next(request)
    path = request.url.path
    if path in _OPEN_PATHS or path.startswith("/static/"):
        return await call_next(request)
    token = request.cookies.get(AUTH_COOKIE, "")
    if token and hmac.compare_digest(token, _expected_token()):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse("/login")


class LoginIn(BaseModel):
    password: str = Field("", max_length=200)


@router.get("/login")
def login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"), headers=NO_CACHE)


@router.post("/api/login")
def login(body: LoginIn):
    credential = load_credential()
    if not credential:
        return {"ok": True}
    if _password_matches(body.password.strip(), credential):
        resp = JSONResponse({"ok": True})
        resp.set_cookie(AUTH_COOKIE, _expected_token(), httponly=True,
                        samesite="lax", max_age=60 * 60 * 24 * 30)
        return resp
    raise HTTPException(401, "wrong password")


@router.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(AUTH_COOKIE)
    return resp
