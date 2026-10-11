@echo off
rem ============================================================
rem  Lance l'appli (fenetre) sans fabriquer de .exe.
rem  Necessite Python installe sur le PC. Double-clique ce fichier.
rem ============================================================
cd /d "%~dp0"
where py >nul 2>nul && (py gui.py) || (python gui.py)
if errorlevel 1 (
  echo.
  echo Echec du lancement. Verifie que Python est installe.
  pause
)
