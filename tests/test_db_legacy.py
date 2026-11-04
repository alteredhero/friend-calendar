"""Opening a database written by an OLD version must upgrade it in place without losing anything."""
import sqlite3
from contextlib import closing

import pytest

import db

LEGACY_SCHEMA = """
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, day TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '', tag TEXT NOT NULL,
    start_min INTEGER NOT NULL DEFAULT 540, end_min INTEGER NOT NULL DEFAULT 600,
    note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE users (name TEXT PRIMARY KEY);
"""


def add_event(conn, day, title="", tag="busy", start=540, end=600, owner="RJ"):
    conn.execute("INSERT INTO events(owner, day, title, tag, start_min, end_min, created_at) "
                 "VALUES(?,?,?,?,?,?,'then')", (owner, day, title, tag, start, end))


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(LEGACY_SCHEMA)
        conn.execute("INSERT INTO users(name) VALUES('RJ')")
        for day in ("2026-11-02", "2026-11-09", "2026-11-16"):   # three look-alike titled events
            add_event(conn, day, title="Work", tag="schedule")
        for day in ("2026-11-03", "2026-11-10"):                  # two look-alike untitled events
            add_event(conn, day, start=1200, end=1300)
        add_event(conn, "2026-11-20", title="Dentist")            # one-off
        conn.commit()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    return path


def columns(path, table):
    with closing(sqlite3.connect(path)) as conn:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_missing_columns_are_added(legacy_db):
    db.init_db()
    assert {"detail", "series_id"} <= columns(legacy_db, "events")
    assert {"color", "timezone"} <= columns(legacy_db, "users")


def test_existing_users_get_sensible_defaults(legacy_db):
    db.init_db()
    with closing(sqlite3.connect(legacy_db)) as conn:
        assert conn.execute("SELECT color, timezone FROM users WHERE name='RJ'").fetchone() == (
            "#6c8cff", db.DEFAULT_TZ)


def test_no_events_are_lost_or_altered(legacy_db):
    db.init_db()
    with closing(sqlite3.connect(legacy_db)) as conn:
        rows = conn.execute("SELECT day, title, tag, start_min, end_min FROM events ORDER BY day").fetchall()
    assert len(rows) == 6
    assert rows[0] == ("2026-11-02", "Work", "schedule", 540, 600)
    assert rows[-1] == ("2026-11-20", "Dentist", "busy", 540, 600)


def test_look_alike_events_are_grouped_into_series(legacy_db):
    db.init_db()
    with closing(sqlite3.connect(legacy_db)) as conn:
        by_day = dict(conn.execute("SELECT day, series_id FROM events"))
    work = {by_day[d] for d in ("2026-11-02", "2026-11-09", "2026-11-16")}
    untitled = {by_day[d] for d in ("2026-11-03", "2026-11-10")}
    assert len(work) == 1 and None not in work
    assert len(untitled) == 1 and None not in untitled
    assert work != untitled
    assert by_day["2026-11-20"] is None  # a group of one is left alone


def test_schema_version_is_recorded(legacy_db):
    db.init_db()
    with closing(sqlite3.connect(legacy_db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_upgrading_twice_changes_nothing(legacy_db):
    db.init_db()
    with closing(sqlite3.connect(legacy_db)) as conn:
        before = conn.execute("SELECT id, series_id FROM events ORDER BY id").fetchall()
    db.init_db()
    with closing(sqlite3.connect(legacy_db)) as conn:
        assert conn.execute("SELECT id, series_id FROM events ORDER BY id").fetchall() == before
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_a_brand_new_database_gets_the_full_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "fresh.db"))
    db.init_db()
    assert {"id", "owner", "day", "title", "tag", "start_min", "end_min", "note",
            "created_at", "detail", "series_id"} <= columns(tmp_path / "fresh.db", "events")
    assert {"name", "color", "timezone"} <= columns(tmp_path / "fresh.db", "users")
