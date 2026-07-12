#define MyAppName "AX4U 교통사고 영상분석기"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "AX4U"
#define MyAppExeName "AX4U_교통사고_영상분석기.exe"

[Setup]
AppId={{98F020A7-4CF9-47C8-A056-2BC8D46E9D0A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AX4U
DefaultGroupName=AX4U
OutputBaseFilename=AX4U_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\AX4U_교통사고_영상분석기.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
