@echo off
setlocal
title Friend Calendar - Quick Share
cd /d "%~dp0\.."

set CF="C:\Program Files (x86)\cloudflared\cloudflared.exe"
set PORT=8032
if defined FRIEND_CALENDAR_PORT set PORT=%FRIEND_CALENDAR_PORT%

REM Is the calendar already being served (e.g. by the tray app)? If so, share THAT one
REM instead of starting a second copy that would just crash on "port in use".
REM (single-term findstr pipes only: findstr treats a space in its pattern as OR)
set RUNNING=0
netstat -ano | findstr /C:":%PORT% " | findstr LISTENING >nul && set RUNNING=1

if "%RUNNING%"=="1" (
  echo Friend Calendar is already running on port %PORT% - sharing that one.
) else (
  echo Starting Friend Calendar on port %PORT% ...
  start "FriendCalendar" cmd /c "py -3.11 main.py"
  timeout /t 3 >nul
)

echo.
echo Opening a public HTTPS tunnel (Quick Tunnel).
echo Look for the https://xxxxx.trycloudflare.com URL below and share it.
echo NOTE: this URL changes every time you run this. Keep this window open.
echo Your password gate still applies. Press Ctrl+C to stop sharing.
echo.
%CF% tunnel --url http://localhost:%PORT%
