#ifndef AppVersion
#define AppVersion "0.0.0"
#endif
; Inno Setup 6 — builds dist\Atelier-Setup.exe from dist\Atelier
[Setup]
AppName=Atelier
AppId={{6C1D2E7A-5B1F-4C0A-9E4A-A7E1B0D3F2C8}
AppVersion={#AppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
DefaultDirName={autopf}\Atelier
DefaultGroupName=Atelier
OutputDir=..\dist
OutputBaseFilename=Atelier-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\Atelier.exe

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Atelier\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\scripts\*.ps1"; DestDir: "{app}\scripts"

[Icons]
Name: "{userstartup}\Atelier"; Filename: "{app}\Atelier.exe"; Tasks: startup
Name: "{group}\Atelier"; Filename: "{app}\Atelier.exe"
Name: "{autodesktop}\Atelier"; Filename: "{app}\Atelier.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Icône sur le bureau"
Name: "startup"; Description: "Lancer Atelier à l'ouverture de session"; Flags: unchecked

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\win-setup.ps1"" -Tier standard"; Description: "Installer les outils manquants (ffmpeg, yt-dlp, Ollama, whisper.cpp, OCR…)"; Flags: postinstall skipifsilent unchecked
Filename: "{app}\Atelier.exe"; Description: "Lancer Atelier"; Flags: postinstall nowait skipifsilent
