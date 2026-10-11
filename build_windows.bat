@echo off
rem ============================================================
rem  Fabrique OpenBuildsVideo.exe (appli Windows autonome).
rem  A lancer UNE FOIS sur un PC Windows (installe Python via winget au besoin).
rem  Resultat : dist\OpenBuildsVideo.exe (+ dist\bin\ffmpeg)
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- Detecter Python (py launcher, puis python reel) ---------------------
rem  Le "python" du Microsoft Store (alias) renvoie une erreur a --version :
rem  on l'ecarte en exigeant que --version reussisse.
set "PY="
where py >nul 2>nul && ( py -3 --version >nul 2>nul && set "PY=py -3" )
if not defined PY ( where python >nul 2>nul && ( python --version >nul 2>nul && set "PY=python" ) )

if not defined PY (
  echo Python non trouve. Tentative d'installation automatique via winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
  rem Re-detecter (le PATH n'est pas rafraichi dans cette fenetre : on cherche aussi le chemin direct).
  where py >nul 2>nul && ( py -3 --version >nul 2>nul && set "PY=py -3" )
  if not defined PY for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do set "PY=%%D\python.exe"
)

if not defined PY (
  echo.
  echo Python est introuvable et n'a pas pu etre installe automatiquement.
  echo Installe-le depuis  https://www.python.org/downloads/
  echo   -^> IMPORTANT : coche "Add Python to PATH" pendant l'installation.
  echo Puis relance ce script.
  goto :err
)

echo Python detecte : %PY%
echo.
echo === Installation des outils de build ===
%PY% -m pip install --upgrade pip pyinstaller edge-tts pyyaml
if errorlevel 1 goto :err

echo.
echo === Construction de l'executable ===
%PY% -m PyInstaller --noconfirm --onefile --windowed --name OpenBuildsVideo ^
  --icon assets\app_icon.ico ^
  --collect-submodules vpipeline ^
  --hidden-import make_video ^
  --collect-all edge_tts ^
  --add-data "config.example.yaml;." ^
  --add-data "assets\app_icon.ico;assets" ^
  --add-data "assets\app_icon_256.png;assets" ^
  gui.py
if errorlevel 1 goto :err

echo.
echo === Telechargement de ffmpeg (pour un exe zero-install) ===
if not exist "dist\bin\ffmpeg.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "try {" ^
    "  $u='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip';" ^
    "  $z=Join-Path $env:TEMP 'ffmpeg_dl.zip';" ^
    "  Write-Host 'Telechargement...'; Invoke-WebRequest -Uri $u -OutFile $z;" ^
    "  $x=Join-Path $env:TEMP 'ffmpeg_x'; if(Test-Path $x){Remove-Item $x -Recurse -Force};" ^
    "  Expand-Archive -Path $z -DestinationPath $x -Force;" ^
    "  New-Item -ItemType Directory -Force -Path 'dist\bin' ^| Out-Null;" ^
    "  Get-ChildItem -Path $x -Recurse -Include ffmpeg.exe,ffprobe.exe ^| ForEach-Object { Copy-Item $_.FullName 'dist\bin' -Force };" ^
    "  Write-Host 'ffmpeg installe dans dist\bin'" ^
    "} catch { Write-Host ('ffmpeg non telecharge: '+$_.Exception.Message) }"
) else (
  echo ffmpeg deja present dans dist\bin
)

echo.
echo ============================================================
echo  OK  -^>  dist\OpenBuildsVideo.exe
echo ============================================================
echo.
if exist "dist\bin\ffmpeg.exe" (
  echo  ffmpeg est embarque : l'exe fonctionne tel quel.
  echo  Distribue le dossier dist\ ^(exe + bin\^) ensemble.
) else (
  echo  ffmpeg n'a pas pu etre telecharge automatiquement.
  echo  Installe-le ^(winget install Gyan.FFmpeg^) ou copie
  echo  ffmpeg.exe et ffprobe.exe dans dist\bin\ manuellement.
)
echo.
pause
exit /b 0

:err
echo.
echo ECHEC du build. Lis les messages ci-dessus.
pause
exit /b 1
