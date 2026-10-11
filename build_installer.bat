@echo off
rem ============================================================
rem  Fabrique l'installateur partageable :
rem     installer_output\GenerateurVideo-Setup.exe
rem
rem  Enchaine : (1) build de l'exe + ffmpeg, (2) compilation Inno Setup.
rem  A lancer sur un PC Windows avec Python installe.
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- 1) S'assurer que dist\GenerateurVideo.exe existe --------------------
if not exist "dist\GenerateurVideo.exe" (
  echo === Etape 1 : construction de l'application ===
  call build_windows.bat
  if errorlevel 1 goto :err
) else (
  echo Application deja construite ^(dist\GenerateurVideo.exe^).
)

rem --- 2) Localiser le compilateur Inno Setup (ISCC.exe) -------------------
set "ISCC="
for %%P in (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
  "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
) do if exist %%P set "ISCC=%%~P"

if not defined ISCC (
  echo.
  echo Inno Setup introuvable. Tentative d'installation via winget...
  winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements
  for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
  ) do if exist %%P set "ISCC=%%~P"
)

if not defined ISCC (
  echo.
  echo Inno Setup n'est pas installe. Installe-le depuis :
  echo    https://jrsoftware.org/isdl.php
  echo puis relance ce script.
  goto :err
)

rem --- 3) Compiler l'installateur -----------------------------------------
echo.
echo === Etape 2 : compilation de l'installateur ===
"%ISCC%" GenerateurVideo.iss
if errorlevel 1 goto :err

echo.
echo ============================================================
echo  OK  -^>  installer_output\GenerateurVideo-Setup.exe
echo ============================================================
echo.
echo  C'est LE fichier a partager. La personne le lance, l'appli
echo  s'installe avec un raccourci Bureau, sans droits admin.
echo.
pause
exit /b 0

:err
echo.
echo ECHEC. Lis les messages ci-dessus.
pause
exit /b 1
