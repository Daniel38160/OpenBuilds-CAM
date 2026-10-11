; ============================================================================
;  Installateur Windows pour OpenBuilds Video (Inno Setup).
;  Produit : installer_output\OpenBuildsVideo-Setup.exe
;
;  Un seul fichier a partager : il installe l'appli, cree un raccourci Bureau
;  et un raccourci dans le menu Demarrer, et ajoute un desinstalleur propre.
;  Installation par utilisateur -> AUCUN droit administrateur requis.
;
;  Prerequis : dist\OpenBuildsVideo.exe doit exister (lance build_windows.bat
;  avant, ou utilise build_installer.bat qui enchaine les deux etapes).
; ============================================================================

#define MyAppName "OpenBuilds Video"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "OpenBuilds Video"
#define MyAppExeName "OpenBuildsVideo.exe"

[Setup]
AppId={{B3B48E59-9147-414C-BE79-2BACF9DF1D00}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\OpenBuildsVideo
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=installer_output
OutputBaseFilename=OpenBuildsVideo-Setup
SetupIconFile=assets\app_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Par utilisateur : pas besoin d'etre administrateur (ideal pour partager).
PrivilegesRequired=lowest

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; \
  GroupDescription: "Raccourcis :"; Flags: checkedonce

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; ffmpeg embarque (si present a cote de l'exe apres build_windows.bat)
Source: "dist\bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
; Episode de demonstration pour tester tout de suite
Source: "episodes\demo\*"; DestDir: "{app}\episodes\demo"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "README.md"; DestDir: "{app}"; Flags: isreadme skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; \
  Flags: nowait postinstall skipwaitforidle
