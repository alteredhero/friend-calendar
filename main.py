"""Friend Calendar - a shared calendar with tagged, time-boxed events.

Run:  python main.py   (or)   uvicorn main:app --host 0.0.0.0 --port 8032
Set the group password first:  python set_password.py
"""
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import instance
import ports
from passwords import ALGORITHM, verify_password
from paths import APP_DIR, DATA_DIR, data_path

DB_PATH = data_path("calendar.db")
STATIC_DIR = os.path.join(APP_DIR, "static")
AUTH_PATH = data_path("auth.json")
SECRET_PATH = data_path(".session_secret")
AUTH_COOKIE = "fc_auth"

HOST = os.environ.get("FRIEND_CALENDAR_HOST", "0.0.0.0")
PORT = int(os.environ.get("FRIEND_CALENDAR_PORT", "8032"))
# Setting FRIEND_CALENDAR_PORT pins the port exactly. Without it, PORT is only the first choice:
# if it's busy we use the next free one (see ports.py).
PORT_PINNED = "FRIEND_CALENDAR_PORT" in os.environ


def pick_port() -> int:
    return ports.choose_port(HOST, PORT, strict=PORT_PINNED)
# how far an edit/delete reaches when an event belongs to a series
SCOPES = ("single", "following", "all")

log = logging.getLogger("friend-calendar")

VALID_TAGS = {"movie", "out of town", "game", "schedule", "busy"}

# US timezones we support (IANA names)
VALID_TZS = {
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Phoenix", "America/Los_Angeles", "America/Anchorage",
    "Pacific/Honolulu",
}
DEFAULT_TZ = "America/Los_Angeles"

app = FastAPI(title="Friend Calendar")


# --------------------------------------------------------------------------- #
# Shared-password gate
# --------------------------------------------------------------------------- #
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


@app.middleware("http")
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


# Browsers (and Cloudflare's edge) must revalidate pages and scripts on every load, so a code
# update can never leave a client running a stale script beside a fresh page. Revalidation is
# cheap: unchanged files come back as a 304 thanks to the ETag.
NO_CACHE = {"Cache-Control": "no-cache"}


class RevalidatingStatic(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.update(NO_CACHE)
        return resp


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"), headers=NO_CACHE)


@app.post("/api/login")
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


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(AUTH_COOKIE)
    return resp


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _backfill_series(conn) -> int:
    """One-time grouping of pre-existing look-alike events into series, so old
    schedules (say, a long run of 'Work' shifts) become bulk-editable.

      titled events   -> same owner + tag + title + detail
      untitled events -> same owner + tag + exact time slot

    A group of one is left alone (its series_id stays NULL).
    The column lists and conditions below are literals, never user input."""
    rules = [
        ("owner, tag, title, detail", "(title != '' OR detail != '')"),
        ("owner, tag, start_min, end_min", "(title = '' AND detail = '')"),
    ]
    made = 0
    for cols, cond in rules:
        names = [c.strip() for c in cols.split(",")]
        match = " AND ".join(f"{n} = ?" for n in names)
        keys = conn.execute(
            f"SELECT {cols} FROM events WHERE series_id IS NULL AND {cond} "
            f"GROUP BY {cols} HAVING COUNT(*) > 1"
        ).fetchall()
        for key in keys:
            conn.execute(
                f"UPDATE events SET series_id = ? WHERE series_id IS NULL AND {cond} AND {match}",
                (uuid.uuid4().hex, *tuple(key)),
            )
            made += 1
    return made


def init_db():
    with closing(db()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                owner      TEXT    NOT NULL,
                day        TEXT    NOT NULL,            -- YYYY-MM-DD
                title      TEXT    NOT NULL DEFAULT '',
                tag        TEXT    NOT NULL,
                start_min  INTEGER NOT NULL DEFAULT 540, -- minutes since midnight
                end_min    INTEGER NOT NULL DEFAULT 600,
                note       TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_day ON events(day);

            CREATE TABLE IF NOT EXISTS users (
                name     TEXT PRIMARY KEY,
                color    TEXT NOT NULL DEFAULT '#6c8cff',
                timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles'
            );
            """
        )
        ucols = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
        if "color" not in ucols:
            conn.execute("ALTER TABLE users ADD COLUMN color TEXT NOT NULL DEFAULT '#6c8cff'")
        if "timezone" not in ucols:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT '{DEFAULT_TZ}'"
            )
        # lightweight migrations
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(events)")]
        if "detail" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN detail TEXT NOT NULL DEFAULT ''")
        if "series_id" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN series_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_series ON events(series_id)")
        # schema v1: group legacy look-alike events into series (runs exactly once)
        if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
            made = _backfill_series(conn)
            conn.execute("PRAGMA user_version = 1")
            log.info("series migration: grouped existing events into %d series", made)
        conn.commit()


init_db()


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EventIn(BaseModel):
    owner: str = Field(..., min_length=1, max_length=40)
    day: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str = Field("", max_length=120)
    tag: str
    start_min: int = Field(540, ge=0, le=1440)
    end_min: int = Field(600, ge=0, le=1440)
    note: str = Field("", max_length=500)
    detail: str = Field("", max_length=120)  # e.g. which game / which movie


class BulkEventIn(BaseModel):
    """Create the same event across many days (multi-select + recurrence)."""
    owner: str = Field(..., min_length=1, max_length=40)
    days: list[str] = Field(..., min_length=1, max_length=400)
    title: str = Field("", max_length=120)
    tag: str
    start_min: int = Field(540, ge=0, le=1440)
    end_min: int = Field(600, ge=0, le=1440)
    note: str = Field("", max_length=500)
    detail: str = Field("", max_length=120)


class EventPatch(BaseModel):
    """Partial update: only the fields actually sent are changed."""
    title: str | None = Field(None, max_length=120)
    tag: str | None = None
    detail: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=500)
    start_min: int | None = Field(None, ge=0, le=1440)
    end_min: int | None = Field(None, ge=0, le=1440)


class UserIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    color: str = Field("#6c8cff", pattern=r"^#[0-9a-fA-F]{6}$")
    timezone: str = Field(DEFAULT_TZ)


def _row_to_dict(r: sqlite3.Row) -> dict:
    return dict(r)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/events")
def list_events(month: str | None = None):
    """List events. Optional month filter as YYYY-MM."""
    with closing(db()) as conn:
        if month:
            rows = conn.execute(
                "SELECT * FROM events WHERE day LIKE ? ORDER BY day, start_min",
                (f"{month}-%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY day, start_min"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


@app.get("/api/users")
def list_users():
    """Managed users (with color + timezone), unioned with any event owners."""
    with closing(db()) as conn:
        rows = conn.execute("SELECT name, color, timezone FROM users").fetchall()
        known = {r["name"]: {"color": r["color"], "timezone": r["timezone"]} for r in rows}
        owners = conn.execute("SELECT DISTINCT owner FROM events").fetchall()
    for o in owners:
        known.setdefault(o["owner"], {"color": "#6c8cff", "timezone": DEFAULT_TZ})
    return [{"name": n, **v}
            for n, v in sorted(known.items(), key=lambda kv: kv[0].lower())]


@app.post("/api/users")
def add_user(u: UserIn):
    name = u.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    tz = u.timezone if u.timezone in VALID_TZS else DEFAULT_TZ
    with closing(db()) as conn:
        conn.execute(
            """INSERT INTO users(name, color, timezone) VALUES(?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET color=excluded.color, timezone=excluded.timezone""",
            (name, u.color, tz),
        )
        conn.commit()
    return {"ok": True, "name": name, "color": u.color, "timezone": tz}


def _check_tag(tag: str):
    if tag not in VALID_TAGS:
        raise HTTPException(400, f"tag must be one of {sorted(VALID_TAGS)}")


def _check_times(start_min: int, end_min: int):
    if end_min <= start_min:
        raise HTTPException(400, "end_min must be after start_min")


def _validate(ev: EventIn):
    _check_tag(ev.tag)
    _check_times(ev.start_min, ev.end_min)


def _find_event(conn, event_id: int):
    return conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


def _get_event(conn, event_id: int):
    row = _find_event(conn, event_id)
    if row is None:
        raise HTTPException(404, "event not found")
    return row


def _check_scope(scope: str) -> str:
    if scope not in SCOPES:
        raise HTTPException(400, f"scope must be one of {list(SCOPES)}")
    return scope


def _scope_where(row, scope: str) -> tuple[str, tuple]:
    """WHERE clause (+ params) selecting the events a scoped action touches.
    An event that isn't part of a series always behaves as 'single'."""
    if scope == "single" or not row["series_id"]:
        return "id = ?", (row["id"],)
    if scope == "all":
        return "series_id = ?", (row["series_id"],)
    return "series_id = ? AND day >= ?", (row["series_id"], row["day"])  # following


@app.post("/api/events")
def create_event(ev: EventIn):
    _validate(ev)
    with closing(db()) as conn:
        cur = conn.execute(
            """INSERT INTO events(owner, day, title, tag, start_min, end_min, note, detail, created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (ev.owner, ev.day, ev.title, ev.tag, ev.start_min, ev.end_min,
             ev.note, ev.detail, datetime.utcnow().isoformat()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM events WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.post("/api/events/bulk")
def create_events_bulk(payload: BulkEventIn):
    """Insert one event per day. Powers multi-day select + recurring events.
    Everything created in one call shares a series_id so it can be edited together."""
    _check_tag(payload.tag)
    _check_times(payload.start_min, payload.end_min)
    days = sorted({d for d in payload.days if _DAY_RE.match(d)})
    if not days:
        raise HTTPException(400, "no valid days provided")
    series_id = uuid.uuid4().hex if len(days) > 1 else None
    now = datetime.utcnow().isoformat()
    with closing(db()) as conn:
        conn.executemany(
            """INSERT INTO events(owner, day, title, tag, start_min, end_min, note, detail, series_id, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [(payload.owner, d, payload.title, payload.tag, payload.start_min,
              payload.end_min, payload.note, payload.detail, series_id, now) for d in days],
        )
        conn.commit()
    return {"ok": True, "created": len(days), "days": days, "series_id": series_id}


@app.put("/api/events/{event_id}")
def update_event(event_id: int, ev: EventIn):
    _validate(ev)
    with closing(db()) as conn:
        _get_event(conn, event_id)  # 404 if missing
        conn.execute(
            """UPDATE events SET owner=?, day=?, title=?, tag=?, start_min=?, end_min=?, note=?, detail=?
               WHERE id=?""",
            (ev.owner, ev.day, ev.title, ev.tag, ev.start_min, ev.end_min,
             ev.note, ev.detail, event_id),
        )
        conn.commit()
        row = _get_event(conn, event_id)
    return _row_to_dict(row)


@app.get("/api/events/{event_id}/series")
def series_info(event_id: int):
    """How big is the series this event belongs to? (An unseried event counts as 1.)"""
    with closing(db()) as conn:
        row = _get_event(conn, event_id)
        where, params = _scope_where(row, "all")
        total, first_day, last_day = conn.execute(
            f"SELECT COUNT(*), MIN(day), MAX(day) FROM events WHERE {where}", params
        ).fetchone()
        where, params = _scope_where(row, "following")
        following = conn.execute(
            f"SELECT COUNT(*) FROM events WHERE {where}", params
        ).fetchone()[0]
    return {"series_id": row["series_id"], "total": total, "following": following,
            "first_day": first_day, "last_day": last_day}


@app.patch("/api/events/{event_id}")
def patch_event(event_id: int, patch: EventPatch, scope: str = "single"):
    """Apply ONLY the fields sent -- to this event, to it and every later event in
    its series ('following'), or to the whole series ('all').

    Sending just what changed is what keeps a bulk edit safe: fixing a tag across a
    series must not flatten each day's individual start/end times."""
    _check_scope(scope)
    # model_dump only yields declared fields, so these column names are a fixed whitelist
    changes = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None}
    if not changes:
        raise HTTPException(400, "nothing to update")
    if "tag" in changes:
        _check_tag(changes["tag"])
    if ("start_min" in changes) != ("end_min" in changes):
        raise HTTPException(400, "send start_min and end_min together")
    if "start_min" in changes:
        _check_times(changes["start_min"], changes["end_min"])
    with closing(db()) as conn:
        row = _get_event(conn, event_id)
        where, params = _scope_where(row, scope)
        sets = ", ".join(f"{col} = ?" for col in changes)
        values = list(changes.values())
        if scope == "following" and row["series_id"]:
            # split: the edited tail becomes its own series, so a later 'entire series'
            # edit on the older part can't reach back into it (and vice versa)
            sets += ", series_id = ?"
            values.append(uuid.uuid4().hex)
        cur = conn.execute(f"UPDATE events SET {sets} WHERE {where}", (*values, *params))
        conn.commit()
        updated = _row_to_dict(_get_event(conn, event_id))
    return {"ok": True, "affected": cur.rowcount, "event": updated}


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, scope: str = "single"):
    _check_scope(scope)
    with closing(db()) as conn:
        row = _find_event(conn, event_id)
        if row is None:
            return {"ok": True, "deleted": 0}  # idempotent, like before
        where, params = _scope_where(row, scope)
        cur = conn.execute(f"DELETE FROM events WHERE {where}", params)
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}



# --------------------------------------------------------------------------- #
# Static / index
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers=NO_CACHE)


app.mount("/static", RevalidatingStatic(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import sys

    import uvicorn

    if not instance.acquire():
        sys.exit(f"Friend Calendar is already running for the data folder {DATA_DIR}")
    port = pick_port()
    if port != PORT:
        print(f"Port {PORT} is busy, so using port {port} instead.")
    print(f"Friend Calendar: open http://localhost:{port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=HOST, port=port)
