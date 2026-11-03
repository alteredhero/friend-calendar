"""Render the tray's calendar icon to packaging/icon.ico (run by build.py, inside the build venv)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tray_app import GREEN, make_icon  # noqa: E402  (reuse the exact icon the tray draws: DRY)

OUT = os.path.join(ROOT, "packaging", "icon.ico")
make_icon(GREEN).save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
print("wrote", OUT)
