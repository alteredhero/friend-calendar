# Hosting Friend Calendar

This guide publishes your calendar at a permanent URL such as **https://calendar.example.com**
(use your own domain wherever you see `example.com`). Friends need only the link and the shared
password; there is no router setup or static IP involved.

**Prerequisites:** a domain whose DNS is on your own (free) Cloudflare account, and
[`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
installed on the PC that runs the calendar. Set your group password first
(`python set_password.py`) and optionally set the `FRIEND_CALENDAR_PUBLIC_URL` environment
variable to your URL so the tray menu gets an "Open public site" item.

The Windows details below (tray app, `cloudflared` as a service) are what the author runs; on
other systems the Cloudflare side is identical and you just keep `python main.py` running.

## How it fits together

```
friends' browsers
      |  https://calendar.example.com             (HTTPS is handled by Cloudflare)
      v
Cloudflare edge
      |  tunnel (cloudflared dials OUT from this PC, so nothing is exposed inbound)
      v
cloudflared  (Windows service on this PC)
      |  http://localhost:8032
      v
Friend Calendar  (tray app: main.py)  -->  calendar.db
```

Two separate pieces both have to be up:

| Piece | What it is | Starts | Quick check |
|---|---|---|---|
| **Calendar app** | `tray_app.py` (headless, tray icon) | when **you log in** | tray icon is green, or http://localhost:8032 answers |
| **Tunnel** | the `cloudflared` Windows service, configured in the Cloudflare dashboard (its token lives in `C:\ProgramData\cloudflared\token`) | at **boot**, automatically | `sc query cloudflared` says `RUNNING` |

**Consequence:** after a reboot the tunnel comes up before you log in, but the app doesn't, so
friends get a Cloudflare error page (usually 502) until you sign in to Windows.

## Where each setting lives

| Setting | Where |
|---|---|
| Hostname and routing | **Cloudflare dashboard**, not a file here (see "Changing the hostname") |
| Shared password | `auth.json`, managed with `python set_password.py` (applies immediately; changing it signs everyone out) |
| Data | `calendar.db` |
| Port | `FRIEND_CALENDAR_PORT` env var (default 8032). If you change it, change the dashboard's service URL too |

## Everyday operations

| I want to... | Do this |
|---|---|
| See if it's up | Tray icon green, or open the URL (the sign-in page means healthy) |
| Restart the app (e.g. after a code change) | Tray icon > **Restart** |
| See what happened | Tray icon > **View log** (`friend-calendar.log`) |
| Take the site offline | Quit the tray app (friends see a 502). To also stop the tunnel: `net stop cloudflared` from an **admin** prompt (`net start cloudflared` brings it back) |
| Back up the data | `py -3.11 -c "import sqlite3; s=sqlite3.connect('calendar.db'); d=sqlite3.connect('calendar.db.bak-manual'); s.backup(d)"` (safe while the server is running) |

## Troubleshooting

| What you see | Likely cause | Fix |
|---|---|---|
| Browser says it **can't find / resolve** the host | The hostname isn't in Cloudflare DNS, usually a **typo**. Easy to do: `calender` is not `calendar` | `nslookup calendar.example.com` should return Cloudflare addresses (104.x / 172.67.x). If not, fix the hostname in the dashboard |
| Cloudflare error page, **502 Bad gateway** | Tunnel is fine but the **app isn't answering** | Is the tray icon missing or red? Start it (`Friend Calendar.bat` > 4, or sign in so autostart runs). Check that `pythonw.exe` owns port 8032 |
| Cloudflare **error 1033** | The **tunnel is offline** | `sc query cloudflared`; start it from an admin prompt: `net start cloudflared` |
| Only some URLs work, or others **404** | The hostname's **Path** field is not empty. We hit this: a leftover `^/blog` limited it to `/blog` | Edit the public hostname and **clear Path** |
| Tray icon is **red** | Port 8032 is taken, e.g. a second `python main.py` is running | Close the other one (`Friend Calendar.bat` shows RUNNING/not running) |

## Changing the hostname (or adding another)

In the Cloudflare dashboard: **Zero Trust > Networks > Tunnels >** your tunnel **> public
hostname > Add**:

- **Subdomain:** `calendar` (double-check the spelling: a typo here is the classic cause of "can't resolve host")
- **Domain:** `example.com` (yours)
- **Path:** *(leave empty)*
- **Service type:** `HTTP`  **URL:** `localhost:8032`

Use **HTTP**, not HTTPS. Cloudflare provides the HTTPS at its edge, and the app speaks plain
HTTP on localhost. Cloudflare creates the DNS record for you.

**Why it has to be a domain you own on Cloudflare:** a tunnel can only publish hostnames from a
zone in your own Cloudflare account. Free-subdomain services don't work for this. We tried:
*is-a.dev* rejects tunnel records outright (its checks fail with `CNAME cannot end with
.cfargotunnel.com`), and *DuckDNS* only supports A/AAAA records, which can't point at a tunnel.

## Throwaway sharing without any Cloudflare setup

`deploy\QuickShare.bat` opens a random `https://<words>.trycloudflare.com` link to the app. It
needs no dashboard configuration, but the link **changes every run** and works only while its
window stays open. Handy for a demo, or if the permanent hostname is broken. It shares the
running app (and only starts one if nothing is serving), and the password gate still applies.

## Security

- Everyone who has the shared password can edit **everything**; there are no per-user accounts.
- The sign-in has **no lockout or rate limit**, and the site is public. Use a **long** password.
- `auth.json`, `.session_secret` and `C:\ProgramData\cloudflared\token` are secrets: don't share
  or commit them. (Deleting `.session_secret` just signs everyone out.)
- For a second gate in front of the app, Cloudflare Access can require a login before anyone
  even reaches the sign-in page.

## Files in this folder

- `hosting-guide.md`: this file.
- `QuickShare.bat`: throwaway public link (see above).

There is deliberately **no tunnel config file** here. Routing lives in the Cloudflare dashboard,
and the service reads its own token. Avoid running a second connector for the same tunnel from a
local config: connectors share a tunnel's traffic, so one with different routing rules would
answer some requests differently from the live one.
