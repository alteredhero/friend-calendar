"""Where things live. One place, so main / tray / backup / set_password never disagree.

APP_DIR   read-only files shipped with the app (static/). Inside the bundle when frozen.
DATA_DIR  your calendar's files (calendar.db, auth.json, .session_secret, the log).

  * running from source:   DATA_DIR is the project folder (unchanged from earlier versions)
  * installed .exe:        DATA_DIR is %LOCALAPPDATA%\\FriendCalendar, so upgrading or
                           uninstalling the program never touches your data
  * either:                set FRIEND_CALENDAR_DATA to use a folder of your choosing
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = getattr(sys, "_MEIPASS", SOURCE_DIR)


def _default_data_dir() -> str:
    if not FROZEN:
        return SOURCE_DIR
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "FriendCalendar")


DATA_DIR = os.environ.get("FRIEND_CALENDAR_DATA") or _default_data_dir()
os.makedirs(DATA_DIR, exist_ok=True)


def data_path(name: str) -> str:
    return os.path.join(DATA_DIR, name)
