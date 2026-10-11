@echo off
rem ============================================================
rem  Verifie que tout le necessaire est present (Python, ffmpeg,
rem  ffprobe, tkinter...) et affiche un rapport clair.
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && ( py -3 --version >nul 2>nul && set "PY=py -3" )
if not defined PY ( where python >nul 2>nul && ( python --version >nul 2>nul && set "PY=python" ) )

if not defined PY (
  echo Python n'est pas installe.
  echo Installe-le depuis https://www.python.org/downloads/ ^(coche "Add Python to PATH"^).
  echo.
  pause
  exit /b 1
)

%PY% check_setup.py
echo.
pause
