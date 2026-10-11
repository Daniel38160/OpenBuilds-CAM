@echo off
rem ============================================================
rem  Lance l'appli (fenetre) sans .exe -> evite le blocage
rem  "Controle intelligent des applications" de Windows.
rem  Necessite Python 3.12/3.13 (python.org) avec tkinter.
rem ============================================================
cd /d "%~dp0"

rem Choisir un Python STABLE qui a tkinter (3.13/3.12/3.11), pas une pre-version.
set "PY="
for %%V in (3.13 3.12 3.11) do if not defined PY ( py -%%V --version >nul 2>nul && set "PY=py -%%V" )
if not defined PY ( where python >nul 2>nul && ( python --version >nul 2>nul && set "PY=python" ) )

if not defined PY (
  echo.
  echo Python 3.12 ^(ou 3.13^) est introuvable.
  echo Installe-le depuis  https://www.python.org/downloads/
  echo   -^> coche "Add Python to PATH" pendant l'installation, puis relance.
  echo.
  pause
  exit /b 1
)

echo Lancement avec %PY% ...
%PY% gui.py
if errorlevel 1 (
  echo.
  echo L'appli s'est fermee avec une erreur ^(voir ci-dessus^).
  echo Si c'est "No module named tkinter" : installe Python depuis python.org
  echo ^(il inclut tkinter^), pas la version du Microsoft Store.
  echo.
  pause
)
