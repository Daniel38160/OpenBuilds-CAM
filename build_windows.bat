@echo off
rem ============================================================
rem  Fabrique GenerateurVideo.exe (appli Windows autonome).
rem  A lancer UNE FOIS sur un PC Windows (installe Python via winget au besoin).
rem  Resultat : dist\GenerateurVideo.exe (+ dist\bin\ffmpeg)
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- Detecter Python STABLE (3.13/3.12/3.11) ----------------------------
rem  On evite les pre-versions (ex: 3.15) : elles n'ont pas de paquets prets
rem  et forcent une compilation qui echoue souvent (DLL bloquee, Cython...).
set "PY="
for %%V in (3.13 3.12 3.11) do if not defined PY ( py -%%V --version >nul 2>nul && set "PY=py -%%V" )

if not defined PY (
  echo Aucune version stable de Python ^(3.11-3.13^) trouvee.
  echo Installation de Python 3.12 via winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
  rem Re-detecter (PATH non rafraichi ici : on tente aussi le chemin direct).
  for %%V in (3.12 3.13 3.11) do if not defined PY ( py -%%V --version >nul 2>nul && set "PY=py -%%V" )
  if not defined PY for /d %%D in ("%LocalAppData%\Programs\Python\Python31*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
)

if not defined PY (
  echo.
  echo Python 3.11/3.12/3.13 introuvable et non installable automatiquement.
  echo Installe Python 3.12 depuis  https://www.python.org/downloads/release/python-3127/
  echo   -^> coche "Add Python to PATH" pendant l'installation, puis relance ce script.
  goto :err
)

echo Python detecte : %PY%
echo.
echo === Installation des outils de build ===
%PY% -m pip install --upgrade pip pyinstaller edge-tts
if errorlevel 1 goto :err
rem PyYAML est optionnel (configs YAML) : on l'installe en best-effort, sans bloquer.
%PY% -m pip install pyyaml 2>nul || echo (PyYAML non installe - optionnel, les configs .json fonctionnent)

echo.
echo === Construction de l'executable ===
%PY% -m PyInstaller --noconfirm --onefile --windowed --name GenerateurVideo ^
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
echo  OK  -^>  dist\GenerateurVideo.exe
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
