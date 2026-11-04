import json
import sqlite3
import zipfile
from contextlib import closing

import pytest

import backup
import paths
from conftest import event_payload


@pytest.fixture
def populated(client, data_dir):
    """The 'old PC': a database with an event, a password hash and a session key."""
    client.post("/api/events", json=event_payload(title="Movie night"))
    (data_dir / "auth.json").write_text(json.dumps({"password_hash": "pbkdf2_sha256$1$00$00"}))
    (data_dir / ".session_secret").write_text("secret-key")
    return data_dir


def switch_to_blank_install(tmp_path, monkeypatch):
    """Re-point backup/paths at an empty second install (the app itself is untouched)."""
    folder = tmp_path / "new_pc"
    folder.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", str(folder))
    return folder


def titles(folder):
    with closing(sqlite3.connect(folder / "calendar.db")) as conn:
        return [r[0] for r in conn.execute("SELECT title FROM events ORDER BY id")]


def test_export_then_import_round_trip(populated, tmp_path, monkeypatch):
    archive = tmp_path / "backup.zip"
    backup.export_backup(str(archive))
    assert set(zipfile.ZipFile(archive).namelist()) == {"calendar.db", "auth.json", ".session_secret"}

    new_folder = switch_to_blank_install(tmp_path, monkeypatch)
    backup.import_backup(str(archive), force=False)
    assert titles(new_folder) == ["Movie night"]
    assert (new_folder / "auth.json").read_text() == (populated / "auth.json").read_text()
    assert (new_folder / ".session_secret").read_text() == "secret-key"


def test_export_without_a_database_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    with pytest.raises(SystemExit):
        backup.export_backup(str(tmp_path / "out.zip"))


def test_import_refuses_to_overwrite_without_force(populated, tmp_path):
    archive = tmp_path / "backup.zip"
    backup.export_backup(str(archive))
    with pytest.raises(SystemExit) as exc:
        backup.import_backup(str(archive), force=False)  # same install: files already exist
    assert "--force" in str(exc.value.code)


def test_force_keeps_the_old_files_as_bak(populated, tmp_path):
    archive = tmp_path / "backup.zip"
    backup.export_backup(str(archive))
    backup.import_backup(str(archive), force=True)
    names = {p.name for p in populated.iterdir()}
    assert any(n.startswith("calendar.db.bak-") for n in names)
    assert any(n.startswith("auth.json.bak-") for n in names)


def test_corrupt_database_is_refused_and_nothing_changes(populated, tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("calendar.db", b"this is not a database")
    before = (populated / "calendar.db").read_bytes()
    with pytest.raises(SystemExit):
        backup.import_backup(str(bad), force=True)
    assert (populated / "calendar.db").read_bytes() == before
    assert not any(".bak-" in p.name for p in populated.iterdir())


def test_a_sqlite_file_that_is_not_ours_is_refused(populated, tmp_path):
    foreign = tmp_path / "other.db"
    with closing(sqlite3.connect(foreign)) as conn:
        conn.execute("CREATE TABLE unrelated(x)")
        conn.commit()
    bad = tmp_path / "foreign.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.write(foreign, "calendar.db")
    with pytest.raises(SystemExit):
        backup.import_backup(str(bad), force=True)


def test_zip_without_a_database_is_refused(populated, tmp_path):
    bad = tmp_path / "empty.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("auth.json", "{}")
    with pytest.raises(SystemExit):
        backup.import_backup(str(bad), force=True)


def test_zip_slip_names_are_never_written(populated, tmp_path, monkeypatch):
    archive = tmp_path / "backup.zip"
    backup.export_backup(str(archive))
    new_pc = switch_to_blank_install(tmp_path, monkeypatch)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(evil, "w") as z:
        for name in src.namelist():
            z.writestr(name, src.read(name))
        z.writestr("../escaped.txt", "nope")
        z.writestr("static/injected.js", "nope")
    backup.import_backup(str(evil), force=False)
    assert not (tmp_path / "escaped.txt").exists()
    assert not (new_pc / "static").exists()
    assert {p.name for p in new_pc.iterdir()} <= {"calendar.db", "auth.json", ".session_secret"}


def test_export_is_a_consistent_snapshot_of_a_database_in_use(populated, tmp_path):
    with closing(sqlite3.connect(populated / "calendar.db")) as busy:
        busy.execute("BEGIN IMMEDIATE")  # a writer holds the database open mid-transaction
        archive = tmp_path / "live.zip"
        backup.export_backup(str(archive))
        busy.rollback()
    assert zipfile.ZipFile(archive).testzip() is None
