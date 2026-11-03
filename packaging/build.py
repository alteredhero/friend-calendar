"""Build the Windows installer:  py -3.11 packaging\\build.py

    1. makes a clean virtualenv in build\\venv and installs requirements-build.txt into it
    2. freezes tray_app.py into build\\dist\\FriendCalendar\\ with PyInstaller
    3. wraps that folder into build\\installer\\FriendCalendar-Setup-<version>.exe with Inno Setup

Needs: Windows, Python 3.10+ with tkinter, and Inno Setup 6 (winget install JRSoftware.InnoSetup).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
VENV_PY = os.path.join(BUILD, "venv", "Scripts", "python.exe")
DIST = os.path.join(BUILD, "dist")
INSTALLER_DIR = os.path.join(BUILD, "installer")
ISCC_CANDIDATES = [
    os.path.join(os.environ.get(var, ""), "Inno Setup 6", "ISCC.exe")
    for var in ("ProgramFiles(x86)", "ProgramFiles")
] + [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe")]


def run(*cmd: str) -> None:
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def find_iscc() -> str:
    found = shutil.which("iscc") or next((p for p in ISCC_CANDIDATES if os.path.exists(p)), None)
    if not found:
        sys.exit("Inno Setup 6 not found. Install it with:  winget install JRSoftware.InnoSetup")
    return found


def read_version() -> str:
    sys.path.insert(0, ROOT)
    from version import __version__
    return __version__


def main() -> None:
    iscc = find_iscc()  # fail fast, before the slow steps
    version = read_version()

    if not os.path.exists(VENV_PY):
        run(sys.executable, "-m", "venv", os.path.join(BUILD, "venv"))
    run(VENV_PY, "-m", "pip", "install", "--quiet", "--upgrade", "pip")
    run(VENV_PY, "-m", "pip", "install", "--quiet", "-r", "requirements-build.txt")
    run(VENV_PY, os.path.join("packaging", "make_icon.py"))

    shutil.rmtree(DIST, ignore_errors=True)
    run(VENV_PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--noconsole",
        "--name", "FriendCalendar",
        "--icon", os.path.join(ROOT, "packaging", "icon.ico"),
        "--add-data", f"{os.path.join(ROOT, 'static')}{os.pathsep}static",
        "--collect-submodules", "uvicorn",
        "--hidden-import", "pystray._win32",
        "--distpath", DIST,
        "--workpath", os.path.join(BUILD, "work"),
        "--specpath", os.path.join(BUILD, "spec"),
        os.path.join(ROOT, "tray_app.py"))

    run(iscc, f"/DAppVersion={version}", f"/DSourceDir={os.path.join(DIST, 'FriendCalendar')}",
        f"/O{INSTALLER_DIR}", os.path.join(ROOT, "packaging", "installer.iss"))
    print(f"\nDone: {os.path.join(INSTALLER_DIR, f'FriendCalendar-Setup-{version}.exe')}")


if __name__ == "__main__":
    main()
