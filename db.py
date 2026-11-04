"""The SQLite database: where it lives, how to open it, and the schema + migrations."""
import logging
import sqlite3
import uuid
from contextlib import closing

from paths import data_path

DB_PATH = data_path("calendar.db")
# timezone given to a person who has none (also the schema default; users.py reuses it)
DEFAULT_TZ = "America/Los_Angeles"

log = logging.getLogger("friend-calendar")


def connect():
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
    with closing(connect()) as conn:
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
