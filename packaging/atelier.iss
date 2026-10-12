; Inno Setup 6 — builds dist\Atelier-Setup.exe from dist\Atelier
[Setup]
AppName=Atelier
AppVersion=0.1.0
DefaultDirName={autopf}\Atelier
DefaultGroupName=Atelier
OutputDir=..\dist
OutputBaseFilename=Atelier-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\Atelier.exe

[Files]
Source: "..\dist\Atelier\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\scripts\win-setup.ps1"; DestDir: "{app}"

[Icons]
Name: "{group}\Atelier"; Filename: "{app}\Atelier.exe"
Name: "{autodesktop}\Atelier"; Filename: "{app}\Atelier.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Icône sur le bureau"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\win-setup.ps1"""; Description: "Installer les outils manquants (ffmpeg, yt-dlp, Ollama) avec winget"; Flags: postinstall skipifsilent unchecked
Filename: "{app}\Atelier.exe"; Description: "Lancer Atelier"; Flags: postinstall nowait skipifsilent
