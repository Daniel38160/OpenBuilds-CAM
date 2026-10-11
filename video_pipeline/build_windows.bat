@echo off
rem ============================================================
rem  Fabrique OpenBuildsVideo.exe (appli Windows autonome).
rem  A lancer UNE FOIS sur un PC Windows avec Python installe.
rem  Resultat : dist\OpenBuildsVideo.exe
rem ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

echo === Installation des outils de build ===
%PY% -m pip install --upgrade pip pyinstaller edge-tts pyyaml
if errorlevel 1 goto :err

echo.
echo === Construction de l'executable ===
%PY% -m PyInstaller --noconfirm --onefile --windowed --name OpenBuildsVideo ^
  --collect-submodules vpipeline ^
  --hidden-import make_video ^
  --collect-all edge_tts ^
  --add-data "config.example.yaml;." ^
  gui.py
if errorlevel 1 goto :err

echo.
echo ============================================================
echo  OK  -^>  dist\OpenBuildsVideo.exe
echo ============================================================
echo.
echo  IMPORTANT : ffmpeg est necessaire a l'execution.
echo    Option A : installe-le une fois  ->  winget install Gyan.FFmpeg
echo    Option B : copie ffmpeg.exe ET ffprobe.exe dans  dist\bin\
echo               (l'appli les detecte automatiquement)
echo.
pause
exit /b 0

:err
echo.
echo ECHEC du build. Lis les messages ci-dessus.
pause
exit /b 1
