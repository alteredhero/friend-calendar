"""Users: name, color and timezone for each person, and the /api/users routes."""
from contextlib import closing

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import db
from db import DEFAULT_TZ

router = APIRouter()

# US timezones we support (IANA names)
VALID_TZS = {
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Phoenix", "America/Los_Angeles", "America/Anchorage",
    "Pacific/Honolulu",
}


class UserIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    color: str = Field("#6c8cff", pattern=r"^#[0-9a-fA-F]{6}$")
    timezone: str = Field(DEFAULT_TZ)


@router.get("/api/users")
def list_users():
    """Managed users (with color + timezone), unioned with any event owners."""
    with closing(db.connect()) as conn:
        rows = conn.execute("SELECT name, color, timezone FROM users").fetchall()
        known = {r["name"]: {"color": r["color"], "timezone": r["timezone"]} for r in rows}
        owners = conn.execute("SELECT DISTINCT owner FROM events").fetchall()
    for o in owners:
        known.setdefault(o["owner"], {"color": "#6c8cff", "timezone": DEFAULT_TZ})
    return [{"name": n, **v}
            for n, v in sorted(known.items(), key=lambda kv: kv[0].lower())]


@router.post("/api/users")
def add_user(u: UserIn):
    name = u.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    tz = u.timezone if u.timezone in VALID_TZS else DEFAULT_TZ
    with closing(db.connect()) as conn:
        conn.execute(
            """INSERT INTO users(name, color, timezone) VALUES(?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET color=excluded.color, timezone=excluded.timezone""",
            (name, u.color, tz),
        )
        conn.commit()
    return {"ok": True, "name": name, "color": u.color, "timezone": tz}
