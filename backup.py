"""Back up your calendar, or move it to another PC / server, as a single zip file.

    python backup.py export [file.zip]          pack the database + password + session key
    python backup.py import file.zip [--force]  unpack into this install

The zip holds everything that makes your calendar *yours*: calendar.db (events and users),
auth.json (the group password hash) and .session_secret (keeps friends signed in). Exporting is
safe while the server is running. Stop the server before importing.

KEEP THE ZIP PRIVATE: it contains your data and password hash.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "calendar.db"
OPTIONAL = ("auth.json", ".session_secret")
KNOWN = (DB_NAME, *OPTIONAL)  # the only names we ever read from a zip (no path tricks possible)


def path_of(name: str) -> str:
    return os.path.join(HERE, name)


def snapshot_db(dest: str) -> None:
    """Consistent copy of the live database (SQLite's online backup, safe mid-write)."""
    with closing(sqlite3.connect(path_of(DB_NAME))) as src, closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)


def check_db(path: str) -> None:
    try:
        with closing(sqlite3.connect(path)) as conn:
            healthy = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            is_ours = conn.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone()
    except sqlite3.DatabaseError:  # e.g. "file is not a database"
        healthy = is_ours = False
    if not (healthy and is_ours):
        sys.exit("That zip's database is damaged or isn't a Friend Calendar one - nothing was changed.")


def export_backup(out_path: str) -> None:
    if not os.path.exists(path_of(DB_NAME)):
        sys.exit(f"No {DB_NAME} found in {HERE} - nothing to back up.")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        snap = os.path.join(tmp, DB_NAME)
        snapshot_db(snap)
        z.write(snap, DB_NAME)
        for name in OPTIONAL:
            if os.path.exists(path_of(name)):
                z.write(path_of(name), name)
        packed = z.namelist()
    print(f"Saved {os.path.abspath(out_path)}")
    print("Contains:", ", ".join(packed))
    print("Keep this file private (it holds your data and password hash).")


def import_backup(zip_path: str, force: bool) -> None:
    with zipfile.ZipFile(zip_path) as z, tempfile.TemporaryDirectory() as tmp:
        names = [n for n in KNOWN if n in z.namelist()]
        if DB_NAME not in names:
            sys.exit(f"{zip_path} has no {DB_NAME} - is it a backup made by this tool?")
        staged = {}
        for name in names:  # read only whitelisted names, into a scratch dir first
            staged[name] = os.path.join(tmp, name)
            with open(staged[name], "wb") as f:
                f.write(z.read(name))
        check_db(staged[DB_NAME])

        clashes = [n for n in names if os.path.exists(path_of(n))]
        if clashes and not force:
            sys.exit(f"This install already has: {', '.join(clashes)}.\n"
                     "Re-run with --force to replace them (the old ones are kept as *.bak-<time>).")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            for name in names:  # DB first: if the server still has it open, we fail before changing anything
                if os.path.exists(path_of(name)):
                    os.replace(path_of(name), f"{path_of(name)}.bak-{stamp}")
                shutil.copyfile(staged[name], path_of(name))
        except PermissionError:
            sys.exit("A file is in use - stop the calendar server first, then run this again.")
    print("Restored:", ", ".join(names))
    if clashes:
        print(f"Previous versions kept as *.bak-{stamp}")
    print("Start the calendar as usual. Your data upgrades itself on first start if needed.")
    if "auth.json" not in names:
        print("Note: the zip had no password; run `python set_password.py` if you want one.")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    if args[:1] == ["export"] and len(args) <= 2:
        export_backup(args[1] if len(args) == 2
                      else f"friend-calendar-backup-{datetime.now():%Y-%m-%d}.zip")
    elif args[:1] == ["import"] and len(args) == 2:
        import_backup(args[1], force)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
