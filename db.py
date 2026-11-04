"""The SQLite database: where it lives, how to open it, and the schema + migrations.

Schema versions
---------------
`PRAGMA user_version` records which schema version a database is at. `MIGRATIONS[i]` upgrades a
database from version i to i+1, and init_db() runs whatever is pending when the app starts.

To change the schema: add a function at the END of MIGRATIONS. Never edit one that has shipped.

Each migration runs in its own transaction (it fully applies or not at all), and before the first
pending migration the app saves a copy of the database next to it as `calendar.db.bak-pre-vN`
(N = the schema version being upgraded to). A database from a NEWER app is refused, not touched.
"""
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


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #
def _migrate_to_1(conn) -> None:
    """Everything the app did before schema versions existed: the base tables, the columns added
    over time, and grouping look-alike events into series. Safe on an empty, an old, or a
    current database."""
    conn.execute(
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_day ON events(day)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            name     TEXT PRIMARY KEY,
            color    TEXT NOT NULL DEFAULT '#6c8cff',
            timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles'
        )
        """
    )
    ucols = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
    if "color" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN color TEXT NOT NULL DEFAULT '#6c8cff'")
    if "timezone" not in ucols:
        conn.execute(
            f"ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT '{DEFAULT_TZ}'"
        )
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(events)")]
    if "detail" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN detail TEXT NOT NULL DEFAULT ''")
    if "series_id" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN series_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_series ON events(series_id)")
    made = _backfill_series(conn)
    log.info("series migration: grouped existing events into %d series", made)


# index i upgrades schema version i -> i+1. Append new migrations; never edit shipped ones.
MIGRATIONS = [_migrate_to_1]


def _has_user_data(conn) -> bool:
    """True once the events table exists: there is something worth protecting."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'events'"
    ).fetchone() is not None


def _snapshot(conn, target: int) -> str:
    """Copy the whole database to `calendar.db.bak-pre-v<target>` (SQLite's online backup)."""
    dest = f"{DB_PATH}.bak-pre-v{target}"
    with closing(sqlite3.connect(dest)) as copy:
        conn.backup(copy)
    return dest


def init_db() -> None:
    """Bring the database up to the newest schema, safely."""
    with closing(connect()) as conn:
        conn.isolation_level = None  # autocommit: transactions below are explicit, so DDL stays atomic
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        target = len(MIGRATIONS)
        if current > target:
            raise RuntimeError(
                f"This calendar's database is from a newer version of Friend Calendar "
                f"(schema {current}; this app understands up to {target}). Install the newer "
                f"app, or restore the backup you made before upgrading. Nothing was changed."
            )
        if current == target:
            return
        if _has_user_data(conn):
            log.info("saved a copy of the database before upgrading: %s", _snapshot(conn, target))
        for version in range(current + 1, target + 1):
            log.info("upgrading the database to schema version %d", version)
            conn.execute("BEGIN IMMEDIATE")
            try:
                MIGRATIONS[version - 1](conn)
                conn.execute(f"PRAGMA user_version = {int(version)}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
