"""Events: models, validation, and the /api/events routes (create, bulk, edit, series scopes, delete)."""
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import db

router = APIRouter()

# how far an edit/delete reaches when an event belongs to a series
SCOPES = ("single", "following", "all")

VALID_TAGS = {"movie", "out of town", "game", "schedule", "busy"}


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


def _row_to_dict(r: sqlite3.Row) -> dict:
    return dict(r)


@router.get("/api/events")
def list_events(month: str | None = None):
    """List events. Optional month filter as YYYY-MM."""
    with closing(db.connect()) as conn:
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


@router.post("/api/events")
def create_event(ev: EventIn):
    _validate(ev)
    with closing(db.connect()) as conn:
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


@router.post("/api/events/bulk")
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
    with closing(db.connect()) as conn:
        conn.executemany(
            """INSERT INTO events(owner, day, title, tag, start_min, end_min, note, detail, series_id, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [(payload.owner, d, payload.title, payload.tag, payload.start_min,
              payload.end_min, payload.note, payload.detail, series_id, now) for d in days],
        )
        conn.commit()
    return {"ok": True, "created": len(days), "days": days, "series_id": series_id}


@router.put("/api/events/{event_id}")
def update_event(event_id: int, ev: EventIn):
    _validate(ev)
    with closing(db.connect()) as conn:
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


@router.get("/api/events/{event_id}/series")
def series_info(event_id: int):
    """How big is the series this event belongs to? (An unseried event counts as 1.)"""
    with closing(db.connect()) as conn:
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


@router.patch("/api/events/{event_id}")
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
    with closing(db.connect()) as conn:
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


@router.delete("/api/events/{event_id}")
def delete_event(event_id: int, scope: str = "single"):
    _check_scope(scope)
    with closing(db.connect()) as conn:
        row = _find_event(conn, event_id)
        if row is None:
            return {"ok": True, "deleted": 0}  # idempotent, like before
        where, params = _scope_where(row, scope)
        cur = conn.execute(f"DELETE FROM events WHERE {where}", params)
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}
