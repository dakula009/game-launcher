; installer.iss — Inno Setup script for My Game Hub
; Compile with Inno Setup (https://jrsoftware.org/isinfo.php)
; → produces MyGameHub_Setup.exe

[Setup]
AppName=My Game Hub
AppVersion=1.4.0
DefaultDirName={autopf}\MyGameHub
DefaultGroupName=My Game Hub
OutputBaseFilename=MyGameHub_Setup
SetupIconFile=assets\icon.ico
Compression=lzma2
SolidCompression=yes
; User data in AppData is preserved on uninstall
UninstallDisplayName=My Game Hub

[Files]
Source: "dist\MyGameHub\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\My Game Hub"; Filename: "{app}\MyGameHub.exe"
Name: "{commondesktop}\My Game Hub"; Filename: "{app}\MyGameHub.exe"

[Run]
Filename: "{app}\MyGameHub.exe"; Description: "Launch My Game Hub"; Flags: postinstall
