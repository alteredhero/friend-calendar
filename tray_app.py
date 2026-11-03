"""Friend Calendar - headless server with a system-tray icon (Windows).

    pythonw tray_app.py              run (no console window; this is what autostart launches)
    python  tray_app.py --install    start automatically when you log in
    python  tray_app.py --uninstall  stop starting automatically

The installed FriendCalendar.exe is this same program frozen with PyInstaller. It also answers
to three one-shot helper commands, used by its tray menu and the installer:
    --set-password           'choose the group password' dialog
    --export-backup          'save a backup' dialog
    --import-backup FILE.zip restore a backup (replaces what is there; old files kept as .bak)

Why a tray app and not a Windows service? Services run in session 0, which has no desktop,
so they can't show a tray icon -- and installing one needs admin rights. A per-user
background app started at login gives you the icon and needs neither. (The trade-off: it
starts when YOU log in, not at machine boot.)
"""
import ctypes
import hashlib
import importlib.util
import logging
import os
import subprocess
import sys
import threading
import webbrowser

from paths import DATA_DIR, FROZEN, data_path

SCRIPT = os.path.abspath(__file__)
LOG_PATH = data_path("friend-calendar.log")
HELPER_FLAGS = {"--set-password", "--export-backup", "--import-backup"}
# Optional: set FRIEND_CALENDAR_PUBLIC_URL (e.g. https://calendar.example.com) to get an
# "Open public site" item in the tray menu.
PUBLIC_URL = os.environ.get("FRIEND_CALENDAR_PUBLIC_URL", "")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "FriendCalendar"
# One tray per data folder: a second launch of the *same* calendar exits quietly, while a
# separate calendar (different FRIEND_CALENDAR_DATA and port) can run beside it.
MUTEX_NAME = "Local\\FriendCalendarTray-" + hashlib.sha1(
    os.path.normcase(DATA_DIR).encode()).hexdigest()[:12]
ERROR_ALREADY_EXISTS = 183
REQUIRED = ("fastapi", "uvicorn", "pystray", "PIL")

GREEN, AMBER, RED = (75, 208, 123), (247, 209, 84), (255, 92, 114)
STATUS = {  # server state -> (badge colour, label)
    "starting": (AMBER, "starting..."),
    "running": (GREEN, "running"),
    "stopped": (RED, "stopped - see the log"),
}


# --------------------------------------------------------------------------- #
# start at login (HKCU Run key: per-user, no admin needed)
# --------------------------------------------------------------------------- #
def pythonw() -> str:
    """pythonw.exe beside the running interpreter (no console window), else the interpreter."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def launch_command() -> list[str]:
    """How to start this app again: autostart, Restart, and the helper dialogs all use it."""
    return [sys.executable] if FROZEN else [pythonw(), SCRIPT]


def autostart_command() -> str:
    return " ".join(f'"{part}"' for part in launch_command())


def spawn(*extra: str) -> None:
    """Start a detached copy of this app (with extra arguments) and don't wait for it."""
    subprocess.Popen([*launch_command(), *extra], cwd=DATA_DIR, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def autostart_enabled() -> bool:
    """True only if the registered command is the one we'd register now (a stale path counts as off)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_NAME)[0] == autostart_command()
    except FileNotFoundError:
        return False


def set_autostart(enabled: bool) -> None:
    import winreg
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_NAME)
    except FileNotFoundError:
        pass  # already off


def missing_packages() -> list[str]:
    return [m for m in REQUIRED if importlib.util.find_spec(m) is None]


# --------------------------------------------------------------------------- #
# plumbing: logging, single instance, error popup
# --------------------------------------------------------------------------- #
def setup_logging() -> None:
    try:  # roll the log over once at startup if it has grown big
        if os.path.getsize(LOG_PATH) > 1_000_000:
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    logging.basicConfig(filename=LOG_PATH, encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout is None or sys.stderr is None:  # pythonw has no console: keep stray output
        sys.stdout = sys.stderr = open(LOG_PATH, "a", buffering=1, encoding="utf-8")


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_mutex = None


def acquire_single_instance() -> bool:
    """A named mutex makes a second launch (e.g. login + manual start) exit quietly."""
    global _mutex
    _mutex = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def release_single_instance() -> None:
    global _mutex
    if _mutex:
        _kernel32.CloseHandle(_mutex)
        _mutex = None


def popup_error(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Friend Calendar", 0x10)  # MB_ICONERROR


# --------------------------------------------------------------------------- #
# the server and the icon
# --------------------------------------------------------------------------- #
class Server:
    """uvicorn on a background thread, so the main thread can own the tray icon."""

    def __init__(self, app, host: str, port: int):
        import uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_config=None,
                                log_level="info", timeout_graceful_shutdown=3)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="uvicorn", daemon=True)

    def start(self) -> None:
        self._thread.start()

    @property
    def state(self) -> str:
        if self._server.started and self._thread.is_alive():
            return "running"
        if self._thread.ident is not None and not self._thread.is_alive():
            return "stopped"  # e.g. the port was already taken: uvicorn exits its thread
        return "starting"

    def stop(self, timeout: float = 8) -> None:
        self._server.should_exit = True
        self._thread.join(timeout)


def make_icon(badge_rgb):
    """A little calendar with a coloured status badge (green / amber / red)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    blue = (108, 140, 255, 255)
    d.rounded_rectangle((4, 10, 60, 60), radius=8, fill=(236, 240, 250, 255))   # page
    d.rounded_rectangle((4, 10, 60, 28), radius=8, fill=blue)                   # header band
    d.rectangle((4, 20, 60, 28), fill=blue)                                     # square off its bottom
    for x in (18, 46):                                                          # binder rings
        d.rounded_rectangle((x - 3, 3, x + 3, 17), radius=3, fill=(52, 60, 96, 255))
    for row in range(2):                                                        # day squares
        for col in range(4):
            x, y = 12 + col * 11, 36 + row * 11
            d.rectangle((x, y, x + 7, y + 7), fill=(150, 160, 190, 255))
    d.ellipse((36, 36, 62, 62), fill=(*badge_rgb, 255), outline=(255, 255, 255, 255), width=3)
    return img


def run() -> None:
    os.chdir(DATA_DIR)
    setup_logging()
    log = logging.getLogger("tray")
    if not acquire_single_instance():
        log.info("another tray instance is already running - exiting")
        return

    import pystray
    import main as calendar  # the FastAPI app (runs its DB migration on import)

    port = calendar.PORT
    local_url = f"http://localhost:{port}"
    server = Server(calendar.app, calendar.HOST, port)
    done = threading.Event()  # set when the tray is shutting down (stops the watcher)

    def open_local(icon, item):
        webbrowser.open(local_url)

    def open_public(icon, item):
        webbrowser.open(PUBLIC_URL)

    def open_log(icon, item):
        open(LOG_PATH, "a").close()  # make sure it exists
        os.startfile(LOG_PATH)

    def toggle_autostart(icon, item):
        set_autostart(not autostart_enabled())

    def open_data_folder(icon, item):
        os.startfile(DATA_DIR)

    def quit_app(icon, item):
        log.info("quit requested")
        done.set()
        server.stop()
        icon.stop()

    def restart(icon, item):
        log.info("restart requested")
        done.set()
        server.stop()
        release_single_instance()  # so the new process can take the mutex
        spawn()
        icon.stop()

    item, menu = pystray.MenuItem, pystray.Menu
    icon = pystray.Icon(
        "friend-calendar", make_icon(AMBER), "Friend Calendar - starting...",
        menu(
            item(lambda i: f"Friend Calendar - {STATUS[server.state][1]} (port {port})",
                 lambda icon, item: None, enabled=False),
            item("Open calendar", open_local, default=True),
            *([item("Open public site", open_public)] if PUBLIC_URL else []),
            menu.SEPARATOR,
            item("Start at login", toggle_autostart, checked=lambda i: autostart_enabled()),
            item("Set group password...", lambda icon, item: spawn("--set-password")),
            item("Back up data...", lambda icon, item: spawn("--export-backup")),
            item("Open data folder", open_data_folder),
            item("View log", open_log),
            item("Restart", restart),
            item("Quit", quit_app),
        ),
    )

    def watch():
        """Keep the badge colour / tooltip in step with the server's real state."""
        last = None
        while True:
            state = server.state
            if state != last:
                colour, label = STATUS[state]
                icon.icon = make_icon(colour)
                icon.title = f"Friend Calendar - {label}"
                icon.update_menu()
                log.info("server state: %s", state)
                if state == "stopped":
                    icon.notify(f"Is port {port} already in use? Check the log.", "Friend Calendar stopped")
                last = state
            if done.wait(2):
                return

    def setup(icon):
        icon.visible = True
        if not calendar.load_credential():
            icon.notify("No group password is set, so anyone who can reach this PC can edit the "
                        "calendar. Right-click this icon > Set group password.", "Friend Calendar")
        server.start()
        threading.Thread(target=watch, name="watch", daemon=True).start()

    log.info("starting (port %s, python %s)", port, sys.executable)
    icon.run(setup)
    log.info("tray exited")


def run_helper(args: list[str]) -> None:
    """One-shot helper commands (no tray, no server). Errors become a message box, because a
    windowed exe has no console to print them to."""
    import backup
    import set_password
    try:
        if "--set-password" in args:
            set_password.run_gui()
        elif "--export-backup" in args:
            backup.export_gui()
        else:
            source = args[args.index("--import-backup") + 1:][:1]
            if not source:
                sys.exit("--import-backup needs the path of a backup .zip")
            backup.import_backup(source[0], force=True)
    except SystemExit as exit_request:
        if isinstance(exit_request.code, str):  # sys.exit("message")
            popup_error(exit_request.code)
            sys.exit(1)
        raise


def main() -> None:
    args = sys.argv[1:]
    if HELPER_FLAGS & set(args):
        run_helper(args)
        return
    if "--install" in args or "--uninstall" in args:
        if "--install" in args:
            if not FROZEN and (missing := missing_packages()):
                sys.exit(f"Missing packages: {', '.join(missing)}\n"
                         "Run:  py -3.11 -m pip install -r requirements-tray.txt")
            set_autostart(True)
            print("Friend Calendar will now start (headless, with a tray icon) when you log in.")
            print("Registered command:", autostart_command())
        else:
            set_autostart(False)
            print("Friend Calendar will no longer start automatically at login.")
        return
    try:
        run()
    except Exception:
        logging.getLogger("tray").exception("fatal error")
        popup_error(f"Friend Calendar failed to start.\nSee the log:\n{LOG_PATH}")
        raise


if __name__ == "__main__":
    main()
