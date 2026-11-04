"""The migration runner: ordering, atomicity, the pre-upgrade snapshot, and the golden v1.1 database."""
import os
import sqlite3
from contextlib import closing

import pytest

import auth
import db
import main

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "v1_1.sql")
ORIGINAL_EVENT_COLUMNS = "id, owner, day, title, tag, start_min, end_min, note, detail, series_id, created_at"


# ---- helpers ------------------------------------------------------------------------------
def make_v1_1(path):
    with closing(sqlite3.connect(path)) as conn:
        with open(FIXTURE, encoding="utf-8") as f:
            conn.executescript(f.read())


def version_of(path) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def columns(path, table):
    with closing(sqlite3.connect(path)) as conn:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def rows(path, sql):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql).fetchall()


def snapshots(path):
    folder, name = os.path.split(str(path))
    return sorted(f for f in os.listdir(folder) if f.startswith(name + ".bak-pre-"))


@pytest.fixture
def v1_1(tmp_path, monkeypatch):
    path = tmp_path / "calendar.db"
    make_v1_1(path)
    monkeypatch.setattr(db, "DB_PATH", str(path))
    return path


def add_column(name):
    def migrate(conn):
        conn.execute(f"ALTER TABLE events ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    migrate.__name__ = f"add_{name}"
    return migrate


# ---- the golden v1.1 database --------------------------------------------------------------
def test_golden_v1_1_data_survives_opening_with_this_version(v1_1):
    before = rows(v1_1, f"SELECT {ORIGINAL_EVENT_COLUMNS} FROM events ORDER BY id")
    users_before = rows(v1_1, "SELECT name, color, timezone FROM users ORDER BY name")
    assert len(before) == 9 and version_of(v1_1) == 1

    db.init_db()

    assert rows(v1_1, f"SELECT {ORIGINAL_EVENT_COLUMNS} FROM events ORDER BY id") == before
    assert rows(v1_1, "SELECT name, color, timezone FROM users ORDER BY name") == users_before
    assert version_of(v1_1) == len(db.MIGRATIONS)
    if len(db.MIGRATIONS) > 1:  # a real upgrade happened: the safety copy must hold the old data
        (copy,) = snapshots(v1_1)
        assert version_of(os.path.join(os.path.dirname(v1_1), copy)) == 1
        assert rows(os.path.join(os.path.dirname(v1_1), copy),
                    f"SELECT {ORIGINAL_EVENT_COLUMNS} FROM events ORDER BY id") == before
    else:
        assert snapshots(v1_1) == []


def test_golden_v1_1_still_works_through_the_api(v1_1, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(auth, "AUTH_PATH", str(tmp_path / "no-password.json"))
    db.init_db()
    client = TestClient(main.app)

    events = client.get("/api/events?month=2026-11").json()
    assert len(events) == 9
    assert {e["title"] for e in events} >= {"Movie night", "Work", "Dentist"}
    assert {u["name"] for u in client.get("/api/users").json()} == {"Alex", "Blake", "Casey", "Dana"}
    work = next(e for e in events if e["title"] == "Work")
    assert client.get(f"/api/events/{work['id']}/series").json()["total"] == 3
    client.post("/api/events", json={"owner": "Alex", "day": "2026-12-01", "title": "New", "tag": "game",
                                     "start_min": 600, "end_min": 700})
    assert len(client.get("/api/events").json()) == 10


# ---- ordering and versions -------------------------------------------------------------------
def test_pending_migrations_run_in_order_and_set_the_version(v1_1, monkeypatch):
    ran = []

    def first(conn):
        ran.append("first"); add_column("alpha")(conn)

    def second(conn):
        ran.append("second"); add_column("beta")(conn)

    monkeypatch.setattr(db, "MIGRATIONS", [db._migrate_to_1, first, second])
    db.init_db()
    assert ran == ["first", "second"]
    assert version_of(v1_1) == 3
    assert {"alpha", "beta"} <= set(columns(v1_1, "events"))
    assert len(rows(v1_1, "SELECT id FROM events")) == 9


def test_nothing_pending_changes_nothing(v1_1):
    db.init_db()
    stamp = os.path.getmtime(v1_1)
    db.init_db()
    assert os.path.getmtime(v1_1) == stamp and snapshots(v1_1) == []


def test_a_brand_new_database_runs_every_migration_without_a_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    monkeypatch.setattr(db, "MIGRATIONS", [db._migrate_to_1, add_column("alpha")])
    db.init_db()
    assert version_of(path) == 2 and "alpha" in columns(path, "events")
    assert snapshots(path) == []  # nothing to protect yet


# ---- atomicity ---------------------------------------------------------------------------------
def test_a_failing_migration_rolls_back_completely(v1_1, monkeypatch):
    def broken(conn):
        add_column("half_done")(conn)   # this part would succeed...
        conn.execute("INSERT INTO events(owner) VALUES('missing required columns')")  # ...this fails

    monkeypatch.setattr(db, "MIGRATIONS", [db._migrate_to_1, broken])
    before = rows(v1_1, f"SELECT {ORIGINAL_EVENT_COLUMNS} FROM events ORDER BY id")
    with pytest.raises(sqlite3.IntegrityError):
        db.init_db()
    assert version_of(v1_1) == 1
    assert "half_done" not in columns(v1_1, "events")        # the ALTER was rolled back too
    assert rows(v1_1, f"SELECT {ORIGINAL_EVENT_COLUMNS} FROM events ORDER BY id") == before


def test_a_later_failure_keeps_the_earlier_migrations(v1_1, monkeypatch):
    def broken(conn):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "MIGRATIONS", [db._migrate_to_1, add_column("alpha"), broken])
    with pytest.raises(RuntimeError):
        db.init_db()
    assert version_of(v1_1) == 2 and "alpha" in columns(v1_1, "events")  # step 2 stuck, step 3 did not


def test_a_failed_upgrade_can_simply_be_retried(v1_1, monkeypatch):
    calls = {"n": 0}

    def flaky(conn):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first attempt fails")
        add_column("alpha")(conn)

    monkeypatch.setattr(db, "MIGRATIONS", [db._migrate_to_1, flaky])
    with pytest.raises(RuntimeError):
        db.init_db()
    db.init_db()
    assert version_of(v1_1) == 2 and "alpha" in columns(v1_1, "events")


# ---- the safety copy ---------------------------------------------------------------------------
def test_snapshot_is_taken_before_upgrading_and_holds_the_old_data(v1_1, monkeypatch):
    monkeypatch.setattr(db, "MIGRATIONS", [db._migrate_to_1, add_column("alpha"), add_column("beta")])
    db.init_db()
    assert snapshots(v1_1) == ["calendar.db.bak-pre-v3"]   # named by the version we upgraded TO
    copy = str(v1_1) + ".bak-pre-v3"
    assert version_of(copy) == 1
    assert "alpha" not in columns(copy, "events")
    assert len(rows(copy, "SELECT id FROM events")) == 9
    assert version_of(v1_1) == 3


def test_snapshot_survives_a_failed_upgrade(v1_1, monkeypatch):
    def broken(conn):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "MIGRATIONS", [db._migrate_to_1, broken])
    with pytest.raises(RuntimeError):
        db.init_db()
    assert snapshots(v1_1) == ["calendar.db.bak-pre-v2"]
    assert len(rows(str(v1_1) + ".bak-pre-v2", "SELECT id FROM events")) == 9


# ---- newer databases ---------------------------------------------------------------------------
def test_a_database_from_a_newer_app_is_refused_and_left_untouched(v1_1):
    with closing(sqlite3.connect(v1_1)) as conn:
        conn.execute("PRAGMA user_version = 99")
    before = v1_1.read_bytes()
    with pytest.raises(RuntimeError, match="newer version"):
        db.init_db()
    assert v1_1.read_bytes() == before and snapshots(v1_1) == []
