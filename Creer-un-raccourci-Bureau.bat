@echo off
rem ============================================================
rem  Cree un raccourci "Generateur de video" sur le Bureau.
rem  Le raccourci lance l'appli directement (sans console noire,
rem  sans droits admin). A lancer UNE FOIS. Necessite Python.
rem ============================================================
setlocal
cd /d "%~dp0"

rem Trouver pythonw.exe (Python sans fenetre console).
set "PYW="
for /f "delims=" %%P in ('py -c "import sys,os;print(os.path.join(sys.base_prefix,'pythonw.exe'))" 2^>nul') do set "PYW=%%P"
if not defined PYW set "PYW=pythonw.exe"

set "TARGET=%~dp0gui.py"
set "ICON=%~dp0assets\app_icon.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$W=New-Object -ComObject WScript.Shell;" ^
  "$p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Generateur de video.lnk';" ^
  "$s=$W.CreateShortcut($p);" ^
  "$s.TargetPath='%PYW%';" ^
  "$s.Arguments='\"%TARGET%\"';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%ICON%';" ^
  "$s.Save()"

if errorlevel 1 (
  echo Echec de la creation du raccourci.
) else (
  echo.
  echo Raccourci cree sur le Bureau : "Generateur de video"
  echo Double-clique dessus pour lancer l'appli ^(sans console, sans admin^).
)
echo.
pause
