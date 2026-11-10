; Inno Setup script for Focus Blocks. Build with packaging\build.ps1, which runs PyInstaller first
; and passes the version: ISCC /DAppVersion=0.4.0 packaging\installer.iss

#define AppName "Focus Blocks"
#define AppExe "FocusBlocks.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{0AEEC446-82A4-4CF2-A08A-73524C442DD1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ajay Boopalan
; Per-user install: no admin prompt, and the Run key below is the user's own.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Focus Blocks
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist
OutputBaseFilename=FocusBlocks-Setup-{#AppVersion}
SetupIconFile=..\build\focusblocks.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Close a running copy before replacing its files (it saves the block in progress on exit).
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "startup"; Description: "Start {#AppName} automatically when I sign in to Windows"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\FocusBlocks\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files from an older build that the new one no longer ships.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Run at sign-in when "startup" is ticked; removed again when it's unticked on a later install, and on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FocusBlocks"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "FocusBlocks"; Flags: deletevalue; Tasks: not startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "StopFocusBlocks"
