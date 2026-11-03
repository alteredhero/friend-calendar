@echo off
setlocal enabledelayedexpansion
title Friend Calendar Launcher
cd /d "%~dp0"

set PORT=8032
if defined FRIEND_CALENDAR_PORT set PORT=%FRIEND_CALENDAR_PORT%

REM ---- pick a Python that actually has fastapi -------------------------------
set PY=
py -3.11 -c "import fastapi" >nul 2>&1 && set PY=py -3.11
if "!PY!"=="" ( python -c "import fastapi" >nul 2>&1 && set PY=python )
if "!PY!"=="" (
  echo [X] Could not find a Python with FastAPI installed.
  echo     Install it with:  py -3.11 -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

REM ---- the windowless twin of that Python (for the tray app) ------------------
set PYW=pythonw
if "!PY!"=="py -3.11" set PYW=pyw -3.11

REM ---- find this machine's LAN IP for friends --------------------------------
set LANIP=localhost
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  set ip=%%a
  set ip=!ip: =!
  echo !ip! | findstr /b "169.254." >nul || set LANIP=!ip!
  goto :gotip
)
:gotip

:menu
cls
echo ============================================
echo            FRIEND  CALENDAR
echo ============================================
echo   Python : !PY!
echo   Local  : http://localhost:%PORT%
echo   LAN    : http://!LANIP!:%PORT%   (share with friends)
call :is_running
if "!RUNNING!"=="1" ( echo   Status : RUNNING on port %PORT% ) else ( echo   Status : not running )
echo ============================================
echo.
echo   [1]  Start server + open in browser   (this window)
echo   [2]  Start server only (no browser)   (this window)
echo   [3]  Just open the browser
echo   [4]  Start in the BACKGROUND (tray icon, no window)
echo   [5]  Start automatically at login
echo   [6]  Stop starting at login
echo   [7]  Set / change the group password
echo   [Q]  Quit
echo.
set /p choice="  Choose: "

if /i "%choice%"=="1" goto start_open
if /i "%choice%"=="2" goto start_only
if /i "%choice%"=="3" goto open_only
if /i "%choice%"=="4" goto tray_start
if /i "%choice%"=="5" goto autostart_on
if /i "%choice%"=="6" goto autostart_off
if /i "%choice%"=="7" goto set_password
if /i "%choice%"=="q" exit /b 0
goto menu

:start_open
call :is_running
if "!RUNNING!"=="1" goto already_running
start "" "http://localhost:%PORT%"
goto run

:start_only
call :is_running
if "!RUNNING!"=="1" goto already_running
goto run

:open_only
start "" "http://localhost:%PORT%"
goto menu

:tray_start
call :is_running
if "!RUNNING!"=="1" goto already_running
start "" !PYW! tray_app.py
echo.
echo   Started in the background. Look for the calendar icon in the system tray
echo   ^(it may be tucked under the ^^ arrow^). Right-click it for options.
timeout /t 3 >nul
goto menu

:autostart_on
echo.
!PY! tray_app.py --install
echo.
pause
goto menu

:autostart_off
echo.
!PY! tray_app.py --uninstall
echo.
pause
goto menu

:set_password
echo.
!PY! set_password.py
echo.
pause
goto menu

:already_running
echo.
echo   Port %PORT% is already in use - the calendar is probably already running
echo   ^(look for its tray icon^). Use option 3 to open it in your browser.
echo.
pause
goto menu

:is_running
REM single-term findstr pipes only: findstr treats a space in its pattern as OR
set RUNNING=0
netstat -ano | findstr /C:":%PORT% " | findstr LISTENING >nul && set RUNNING=1
exit /b 0

:run
echo.
echo   Starting server on port %PORT% ... (press Ctrl+C in this window to stop)
echo.
!PY! main.py
echo.
echo   Server stopped.
pause
goto menu
