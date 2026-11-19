; Inno Setup script - ينشئ ملف التثبيت NetSpeedMonitor_Setup.exe
[Setup]
AppName=Net Speed Monitor
AppVersion=1.0
DefaultDirName={autopf}\NetSpeedMonitor
DefaultGroupName=Net Speed Monitor
OutputDir=installer_output
OutputBaseFilename=NetSpeedMonitor_Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\NetSpeedMonitor.exe
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "startup"; Description: "Start with Windows (in the system tray)"; GroupDescription: "Additional options:"

[Files]
Source: "dist\NetSpeedMonitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Net Speed Monitor"; Filename: "{app}\NetSpeedMonitor.exe"
Name: "{autodesktop}\Net Speed Monitor"; Filename: "{app}\NetSpeedMonitor.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "NetSpeedMonitor"; ValueData: """{app}\NetSpeedMonitor.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\NetSpeedMonitor.exe"; Description: "Launch Net Speed Monitor"; Flags: nowait postinstall skipifsilent
