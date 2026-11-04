"""Shared fixtures. Every test gets its own throwaway data folder and database.

The app reads its data location when it is imported, so we point it at a scratch folder *before*
importing it, then re-point it (monkeypatch) at a fresh folder for each test.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["FRIEND_CALENDAR_DATA"] = tempfile.mkdtemp(prefix="friend_calendar_tests_")
os.environ.pop("FRIEND_CALENDAR_PORT", None)

import pytest  # noqa: E402

import main  # noqa: E402
import paths  # noqa: E402
from passwords import hash_password  # noqa: E402


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fresh, empty data folder with an initialised database and no password."""
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "calendar.db"))
    monkeypatch.setattr(main, "AUTH_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setattr(main, "SECRET_PATH", str(tmp_path / ".session_secret"))
    main.init_db()
    return tmp_path


@pytest.fixture
def client(data_dir):
    from fastapi.testclient import TestClient
    return TestClient(main.app, follow_redirects=False)


@pytest.fixture
def set_password(data_dir):
    """Call with a password to turn the gate on (hashed, like set_password.py), or '' for off."""
    def _set(password: str) -> None:
        import json
        value = hash_password(password) if password else ""
        (data_dir / "auth.json").write_text(json.dumps({"password_hash": value}), encoding="utf-8")
    return _set


def event_payload(**overrides) -> dict:
    base = {"owner": "RJ", "day": "2026-11-05", "title": "Movie night", "tag": "movie",
            "start_min": 1200, "end_min": 1320, "note": "", "detail": "Dune"}
    return {**base, **overrides}
