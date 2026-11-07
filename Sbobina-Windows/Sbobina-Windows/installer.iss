; Script per Inno Setup: crea Sbobina-Setup.exe dopo aver eseguito build_exe.bat
[Setup]
AppName=Sbobina
AppVersion=0.1
DefaultDirName={autopf}\Sbobina
DefaultGroupName=Sbobina
OutputBaseFilename=Sbobina-Setup
Compression=lzma2
SolidCompression=yes
DiskSpanning=no

[Files]
Source: "dist\Sbobina\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Sbobina"; Filename: "{app}\Sbobina.exe"
Name: "{autodesktop}\Sbobina"; Filename: "{app}\Sbobina.exe"

[Run]
Filename: "{app}\Sbobina.exe"; Description: "Avvia Sbobina"; Flags: nowait postinstall skipifsilent
