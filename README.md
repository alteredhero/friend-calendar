# Friend Calendar

A shared calendar for you and your friends, served by uvicorn (FastAPI + SQLite, no build step).
Each group runs **its own copy** with its own database and its own password. Nothing is shared
between installs.

> ### Disclaimer: built with AI
> This project was created with the help of AI tools (an AI coding assistant wrote and edited
> much of the code and documentation under human direction). AI-generated code can contain
> bugs and security flaws that are easy to miss. **Review it yourself before relying on it,**
> especially before exposing it to the internet or storing anything sensitive in it.
>
> It is a small hobby app with a single shared password and no login rate limiting, not a hardened
> product. It is provided **"as is", without warranty of any kind**, and you use it at your own
> risk. Don't put secrets, passwords or private information in event titles or notes.

## Install on Windows (easiest, no Python needed)
1. Download **`FriendCalendar-Setup-<version>.exe`** from the
   [Releases page](https://github.com/alteredhero/friend-calendar/releases/latest).
2. Run it. No admin rights needed. Windows SmartScreen may say "unknown publisher" because the
   installer isn't code-signed: choose **More info > Run anyway**, but only for a file you got
   from the Releases page.
3. The wizard asks, optionally, for a **backup zip** to restore (moving from another PC?) and
   whether to start the calendar when you sign in. At the end it asks you to **choose the group
   password**.
4. A calendar icon appears in the system tray (it may hide under the `^` arrow). Click it to open
   the calendar in your browser, or share `http://<your-ip>:8032` with friends on your network.
   (If 8032 is busy, the app picks the next free port and tells you; see
   [If port 8032 is busy](#if-port-8032-is-busy).)

Right-click the tray icon for **Set group password...**, **Back up data...**, **Open data
folder**, **Start at login**, **View log**, **Restart** and **Quit**.

- Your data lives in `%LOCALAPPDATA%\FriendCalendar` (events, password hash, log), **separate
  from the program**. Upgrading is just running a newer installer over the old one, and
  uninstalling keeps your data (delete that folder to erase it).
- Windows may show a firewall prompt the first time; allow **private networks** so friends on
  your Wi-Fi can connect.
- Prefer running from source (any OS)? Use the quick start below.

## Quick start from source (make your own calendar)
You need **Python 3.10+**. Works on Windows, macOS and Linux.

```bash
git clone https://github.com/alteredhero/friend-calendar.git
cd friend-calendar

python -m venv .venv                      # optional but tidy
.venv\Scripts\activate                    # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

python set_password.py                    # 1. choose your group's password
python main.py                            # 2. start the calendar
```

Open http://localhost:8032 (the console prints the real address if that port was busy), enter
the password, then pick (or add) yourself as a user.
That's it. Your database (`calendar.db`) is created automatically on first run.

To let friends in, see [Sharing it with your friends](#sharing-it-with-your-friends).

## Group password
The whole group shares **one password**. Set or change it any time:

```bash
python set_password.py           # prompts twice (typing is hidden), min 8 characters
python set_password.py --clear   # remove the password: anyone who can reach the server gets in
```

- It's saved as a salted PBKDF2 **hash** in `auth.json`, never as plain text. `auth.json` is
  git-ignored, so your password can't be committed by accident.
- No restart needed: the server re-reads `auth.json` on every request.
- **Changing the password signs everyone out**; they sign in again with the new one.
- On Windows you can also use the launcher menu (`Friend Calendar.bat` > option 7).
- With no password set, the server logs a loud warning on start. Fine for trying it on your own
  machine, not fine for anything reachable from the internet.
- There are no per-person accounts and no login rate limit, so pick a **long** password
  (a few random words is great).

## Sharing it with your friends
| Where your friends are | What to do |
|---|---|
| Same Wi-Fi / LAN | Share `http://<your-ip>:8032`. You may need to allow the port through your firewall. |
| Anywhere (quick, temporary) | Windows: run `deploy\QuickShare.bat` for a throwaway public `trycloudflare.com` link (needs [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)). |
| Anywhere (permanent URL) | A Cloudflare Tunnel on a domain you own. Full walkthrough in [`deploy/hosting-guide.md`](deploy/hosting-guide.md). |

The server is plain HTTP; put HTTPS in front of it (the tunnel does this for you) before sending
a password over the internet.

## Backups, and moving to a new PC or server
Everything that makes your calendar *yours* is three git-ignored files: `calendar.db` (events and
users), `auth.json` (password hash) and `.session_secret` (keeps friends signed in).
`backup.py` packs them into one zip and unpacks them again:

```bash
python backup.py export                       # -> friend-calendar-backup-YYYY-MM-DD.zip
python backup.py export my-backup.zip         # or pick the name
python backup.py import my-backup.zip         # restore into this install
python backup.py import my-backup.zip --force # replace data that's already here
```

- With the **Windows installer**, use the tray menu's **Back up data...**, and pick the zip on
  the installer's "Restore a backup" page when you set up the new PC. The rest of this section
  describes the command line, which works the same from source.
- **Exporting is safe while the server is running**, so it doubles as your regular backup. Copy
  the zip somewhere other than this machine now and then.
- **Keep the zip private.** It contains your data and your password hash. Zips are git-ignored.
- Importing checks the database first and **refuses a damaged or foreign file without touching
  anything**. With `--force`, whatever it replaces is kept as `*.bak-<timestamp>`.
- **Stop the server before importing** (the importer tells you if a file is still in use).

### Moving to a new PC or a dedicated server
1. **Old machine:** `python backup.py export`, then copy the zip to the new machine
   (USB stick, `scp`, cloud drive, whatever).
2. **New machine:** do the [Quick start](#quick-start-make-your-own-calendar) up to the
   `pip install` step. **Skip** `set_password.py`, because your password comes with the zip.
3. `python backup.py import friend-calendar-backup-....zip`
4. `python main.py`. Your events, users and password are all there, and friends stay signed in.
5. **Point friends at the new place.** On a LAN that's the new IP. With a Cloudflare tunnel,
   move the tunnel connector as described in the
   [hosting guide](deploy/hosting-guide.md#moving-the-tunnel-to-a-new-machine) and the same URL
   keeps working.
6. Once happy, retire the old install (stop it, and turn off start-at-login if you used the tray).

Use the same or a newer version of the code on the new machine. A database from an older version
upgrades itself on first start, but an old copy of the code may not understand a newer database.

On a Linux server you'll want it to start at boot. A minimal `systemd` unit:
```ini
[Unit]
Description=Friend Calendar
After=network.target

[Service]
WorkingDirectory=/opt/friend-calendar
ExecStart=/opt/friend-calendar/.venv/bin/python main.py
Restart=on-failure
User=friendcal

[Install]
WantedBy=multi-user.target
```

## Configuration
All optional, set as environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `FRIEND_CALENDAR_PORT` | *(unset: starts at `8032` and roams)* | **pins** the port: use exactly this one and fail if it's taken |
| `FRIEND_CALENDAR_HOST` | `0.0.0.0` | interface to bind (`127.0.0.1` = this machine only) |
| `FRIEND_CALENDAR_PUBLIC_URL` | *(none)* | Windows tray only: adds an "Open public site" menu item |
| `FRIEND_CALENDAR_DATA` | project folder (source) / `%LOCALAPPDATA%\FriendCalendar` (installed .exe) | where `calendar.db`, `auth.json`, `.session_secret` and the log live |

### If port 8032 is busy
By default the calendar *starts* at port 8032 and, if something else is using it, quietly moves up
to the next free port (8033, 8034, ...). You'll see this in three places: the tray menu header
(`... (port 8033)`), a tray notification, and the log (or the console when run from source).
The tray's **Open calendar** always opens the right one.

Because the address changes, remember:
- **Friends on your network** need the new port in the link (`http://<your-ip>:8033`).
- **A Cloudflare tunnel points at one fixed port**, so a roamed port would show friends a 502 error
  while the tray looks healthy. If you host through a tunnel, **pin the port** so it can never move
  (the app then reports an error instead). Windows: `setx FRIEND_CALENDAR_PORT 8032`, then restart
  the tray. Elsewhere: export `FRIEND_CALENDAR_PORT=8032` in whatever starts the app.
- Only one copy runs per data folder (a small `.instance.lock` file enforces it), so roaming can't
  start a second server on the same calendar. Separate calendars (different
  `FRIEND_CALENDAR_DATA`) can run side by side; each roams to its own port.

Personal files that stay on your machine and are **never committed**: `auth.json` (password
hash), `.session_secret` (cookie signing key), `calendar.db*` (your data) and `*.log`.

## Features
- **Month calendar** with a **snapshot** of the focused day above it and a per-person
  24h **timeline** below it. Ctrl/Shift-click days to multi-select.
- **Tags**: movie, out of town, game, schedule, busy. Movie/game events also record *which*
  movie/game. Start/end are set with sliders **or** typed times.
- **Recurring events**: weekly, bi-weekly, monthly, annually (month-ends and leap days clamp
  sensibly, e.g. Jan 31 monthly -> Feb 28).
- **Timezones**: every user has a US timezone. Events are stored in the *owner's* local time
  and shown converted to the viewer's (DST-aware), with a live US-timezone table on top.
- **Scheduling assistant**: tick the people involved and see when they're all free.
- **Users** with their own color; you must pick who you are before adding events.
- **Shared-password gate** (see above), **headless tray mode** (Windows), and **start at login**.

## Editing and deleting recurring schedules
Anything created across several days (multi-select or recurring) is saved as a **series**, and
a series chip shows a small arrow mark. Open any event of a series and an **Apply to** choice
appears:

| Choice | Save / Delete affects |
|---|---|
| This event only | just that one |
| This and following events | it and every later event in the series |
| Entire series | every event in the series |

Things worth knowing:
- **Save only applies the fields you actually changed.** Fixing a tag across 100 shifts will
  *not* touch each day's own start/end time. Times change only if you edit the time controls.
- **"This and following" splits the series.** Say you change jobs: open the first shift of the
  new schedule, choose "This and following", and edit or delete from there on. The older
  events stay as they were and a later "Entire series" edit on them can't reach the new ones.
- Changing which *days* a schedule runs on = delete (following/all), then add the new schedule.
- The small x on a chip always deletes just that one event.
- The time controls show the **owner's** local time (the label says whose and which zone).
- Events that already existed were grouped into series automatically the first time the
  server started after this feature landed (same owner + tag + title; untitled ones by exact
  time slot). A snapshot of the database from just before that is kept as
  `calendar.db.bak-<date>`; delete it once you're happy.

## Running it
**On Windows, double-click `Friend Calendar.bat`** for a menu: start in this window, open the
browser, start in the background, turn start-at-login on/off, or set the group password. It shows
whether the server is already running (and won't start a second copy on top of it). On other
systems just run `python main.py`.

### Headless with a tray icon (Windows, recommended for hosting)
The tray needs two extra packages: `py -3.11 -m pip install -r requirements-tray.txt`.
```bat
pyw -3.11 tray_app.py              :: run with no console window
py  -3.11 tray_app.py --install    :: start automatically when you log in
py  -3.11 tray_app.py --uninstall  :: stop starting at login
```
A calendar icon appears in the system tray (Windows may tuck it under the `^` arrow; drag it out
to keep it visible). Its corner dot is **green** (running), **amber** (starting) or **red**
(stopped, e.g. a pinned port is taken or startup failed: see the log). Left-click opens the calendar; right-click gives
*Open public site* (only if `FRIEND_CALENDAR_PUBLIC_URL` is set), *Start at login*, *View log*, *Restart* and *Quit*. Output goes to
`friend-calendar.log` (rolled over at ~1 MB).

This is a per-user background app rather than a Windows service on purpose: services run where
there is no desktop, so they can't show a tray icon, and installing one needs admin. The
trade-off is that it starts when **you log in**, not at machine boot.

### Manual
```bat
py -3.11 main.py            :: or: uvicorn main:app --host 0.0.0.0 --port 8032
```
Open http://localhost:8032. For friends on your LAN share `http://<your-ip>:8032` (you may need
to allow port 8032 through Windows Firewall). Install the dependencies with
`py -3.11 -m pip install -r requirements.txt`.

> After an update, a device that still shows a broken page needs one hard refresh (Ctrl+F5).
> The server now tells browsers to revalidate, so this shouldn't recur.

## Running the tests
GitHub Actions runs everything on each push and pull request (`.github/workflows/ci.yml`). Locally:

```bash
python -m venv .venv                   # then activate it, as in the quick start
pip install -r requirements-dev.txt
python -m pytest                       # API, auth, backup, ports, instance lock
node --test "tests/js/**/*.test.js"    # the pure helpers in static/lib.js (needs Node 22+)
```

## Building the Windows installer (maintainers)
The installer is a PyInstaller-frozen `tray_app.py` wrapped by [Inno Setup](https://jrsoftware.org/isinfo.php).
You need Windows, Python 3.10+ (with tkinter) and Inno Setup 6
(`winget install JRSoftware.InnoSetup`). Then:

```bat
py -3.11 packaging\build.py
```

It builds in a clean virtualenv under `build\` and writes
`build\installer\FriendCalendar-Setup-<version>.exe`. The `build\` folder and `*.exe` files are
git-ignored; binaries belong on a Release, not in the repo.

To publish a release, let GitHub Actions do it (`.github/workflows/release.yml`):
1. Bump `__version__` in `version.py`, commit and push.
2. Tag and push the tag: `git tag v<version>` then `git push origin v<version>`.
3. The workflow builds the installer on a Windows runner and publishes the Release with the
   installer, a `SHA256SUMS.txt`, and the checksum in the notes. It refuses to run if the tag
   doesn't match `version.py`.

To try a build without releasing anything, use **Actions > Build Windows installer > Run
workflow**; the installer is attached to the run as an artifact. You can also build locally with
`packaging\build.py` as above.

The installer is **not code-signed**, so Windows SmartScreen warns on first run, and some
antivirus tools are suspicious of any PyInstaller program. Signing needs a paid certificate;
until then, the source here is the thing to trust, and you can always build the installer yourself.

## Hosting it on the internet
See **`deploy/hosting-guide.md`**: how the Cloudflare tunnel, the hostname and the tray app fit
together, everyday operations, and a troubleshooting table of the problems we actually hit.

The session cookie is signed with `.session_secret` (auto-created; don't share it, deleting it
just signs everyone out).

## Files
```
main.py             wires the app together; `python main.py` starts it
auth.py             shared-password gate and login routes
events.py           event models and /api/events routes
users.py            user models and /api/users routes
db.py               SQLite: location, connections, schema (auto-migrates on start)
web.py              static-file helpers
passwords.py        password hashing helper (PBKDF2, stdlib only)
ports.py            finds a free port when the preferred one is busy
instance.py         one running copy per data folder (lock file)
paths.py            where the app's files and your data live (source vs. installed)
version.py          the version number (used by the installer build)
tests/              pytest suite (tests/*.py) and node tests for lib.js (tests/js/)
packaging/          Windows installer: build.py, installer.iss, icon + disclaimer text
requirements-build.txt  extra tooling to build the installer
set_password.py     CLI to set / change / clear the group password
backup.py           export / import everything as one zip (backups and moving house)
auth.example.json   shape of auth.json (your real one is git-ignored)
tray_app.py         headless runner with the tray icon (Windows)
Friend Calendar.bat launcher menu (Windows)
deploy/             hosting guide + QuickShare.bat
static/lib.js       pure helpers + shared constants (no DOM, unit-testable in node)
static/assistant.js scheduling assistant
static/modal.js     the add/edit/delete dialog (incl. series scopes)
static/app.js       state, data loading, calendar/snapshot/timeline views
```
The four scripts are classic `<script>`s sharing one global scope, so **load order matters**
(see `index.html`; `app.js` calls `init()` last).

## API
- `GET  /api/events?month=YYYY-MM`
- `POST /api/events` (single event) and `POST /api/events/bulk` (one event per day in `days`;
  a multi-day call gets a shared `series_id`)
- `PUT  /api/events/{id}` full replace of one event
- `PATCH /api/events/{id}?scope=single|following|all` partial update: only the fields sent
  (`title, tag, detail, note, start_min, end_min`; the two times must be sent together)
- `DELETE /api/events/{id}?scope=single|following|all`
- `GET  /api/events/{id}/series` -> `{series_id, total, following, first_day, last_day}`
- `GET /api/users`, `POST /api/users` (`name`, `color`, `timezone`)

`start_min` / `end_min` are minutes since midnight in the owner's timezone (0-1440).

## License
[MIT](LICENSE). Use it, change it, share it. The AI-assistance disclaimer at the top of this
README still applies: the software is provided as is, without warranty.
