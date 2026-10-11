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
%PY% -m pip install --upgrade pip pyinstaller edge-tts anthropic
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
  --collect-all anthropic ^
  --add-data "config.example.yaml;." ^
  --add-data "assets\app_icon.ico;assets" ^
  --add-data "assets\app_icon_256.png;assets" ^
  gui.py
if errorlevel 1 goto :err

echo.
echo === ffmpeg ===
where ffmpeg >nul 2>nul
if %errorlevel%==0 (
  echo ffmpeg est deja installe sur ce PC : rien a telecharger.
  echo L'exe l'utilisera automatiquement.
  goto :okmsg
)
if exist "dist\bin\ffmpeg.exe" (
  echo ffmpeg deja present dans dist\bin.
  goto :okmsg
)

rem ffmpeg absent : on le telecharge dans dist\bin (curl + tar, integres a Windows 10/11).
echo ffmpeg introuvable : telechargement dans dist\bin ...
if not exist "dist\bin" mkdir "dist\bin"
curl -L -o "%TEMP%\ffmpeg_dl.zip" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
if errorlevel 1 goto :noffmpeg
if exist "%TEMP%\ffmpeg_x" rmdir /s /q "%TEMP%\ffmpeg_x"
mkdir "%TEMP%\ffmpeg_x"
tar -xf "%TEMP%\ffmpeg_dl.zip" -C "%TEMP%\ffmpeg_x"
if errorlevel 1 goto :noffmpeg
for /r "%TEMP%\ffmpeg_x" %%f in (ffmpeg.exe ffprobe.exe) do copy /y "%%f" "dist\bin\" >nul 2>nul
if exist "dist\bin\ffmpeg.exe" (echo ffmpeg installe dans dist\bin.) else (goto :noffmpeg)

:okmsg
echo.
echo ============================================================
echo  OK  -^>  dist\GenerateurVideo.exe
echo ============================================================
echo.
echo  Pour toi : l'exe marche tel quel (ffmpeg deja la ou embarque).
echo  Pour PARTAGER a quelqu'un sans ffmpeg : distribue le dossier dist\
echo  avec le sous-dossier bin\ s'il existe.
echo.
pause
exit /b 0

:noffmpeg
echo.
echo ============================================================
echo  OK  -^>  dist\GenerateurVideo.exe  (ffmpeg non embarque)
echo ============================================================
echo.
echo  ffmpeg n'a pas pu etre telecharge, mais ce n'est PAS grave si
echo  ffmpeg est deja installe sur le PC qui lance l'exe.
echo  Sinon : winget install Gyan.FFmpeg, ou copie ffmpeg.exe et
echo  ffprobe.exe dans dist\bin\.
echo.
pause
exit /b 0

:err
echo.
echo ECHEC du build. Lis les messages ci-dessus.
pause
exit /b 1
