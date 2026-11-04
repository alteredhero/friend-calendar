"""Friend Calendar - a shared calendar with tagged, time-boxed events.

Run:  python main.py   (or)   uvicorn main:app --host 0.0.0.0 --port 8032
Set the group password first:  python set_password.py

This file only wires things together. The pieces:
  auth.py    shared-password gate and login routes
  events.py  event models and /api/events routes
  users.py   user models and /api/users routes
  db.py      the SQLite database: location, connections, schema and migrations
  web.py     static-file helpers
"""
import os
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse

import auth
import db
import events
import instance
import ports
import users
from paths import DATA_DIR
from web import NO_CACHE, STATIC_DIR, RevalidatingStatic

HOST = os.environ.get("FRIEND_CALENDAR_HOST", "0.0.0.0")
PORT = int(os.environ.get("FRIEND_CALENDAR_PORT", "8032"))
# Setting FRIEND_CALENDAR_PORT pins the port exactly. Without it, PORT is only the first choice:
# if it's busy we use the next free one (see ports.py).
PORT_PINNED = "FRIEND_CALENDAR_PORT" in os.environ


def pick_port() -> int:
    return ports.choose_port(HOST, PORT, strict=PORT_PINNED)


app = FastAPI(title="Friend Calendar")
app.middleware("http")(auth.auth_gate)
app.include_router(auth.router)
app.include_router(events.router)
app.include_router(users.router)

auth.warn_if_open()
db.init_db()


# --------------------------------------------------------------------------- #
# Static / index
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers=NO_CACHE)


app.mount("/static", RevalidatingStatic(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    if not instance.acquire():
        sys.exit(f"Friend Calendar is already running for the data folder {DATA_DIR}")
    port = pick_port()
    if port != PORT:
        print(f"Port {PORT} is busy, so using port {port} instead.")
    print(f"Friend Calendar: open http://localhost:{port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=HOST, port=port)
