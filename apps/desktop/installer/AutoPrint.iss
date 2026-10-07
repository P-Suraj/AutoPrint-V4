; AutoPrint Windows installer (Inno Setup 6). Built by installer\build.ps1 -- do not run this file by hand.
; Per-user install: no administrator rights, nothing outside the user's own folders.

#ifndef AppVersion
  #define AppVersion "4.0.4"
#endif
#ifndef SourceDir
  #error SourceDir must be passed by build.ps1
#endif

[Setup]
AppId={{6E1B6F0A-2C7D-4B3F-9D52-A1B2C3D4E5F6}
AppName=AutoPrint
AppVersion={#AppVersion}
AppVerName=AutoPrint {#AppVersion}
AppPublisher=Suraj Pandavula
AppCopyright=Copyright (c) 2026 Suraj Pandavula
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=Suraj Pandavula
VersionInfoProductName=AutoPrint
VersionInfoDescription=AutoPrint Setup
DefaultDirName={localappdata}\Programs\AutoPrint
DefaultGroupName=AutoPrint
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=AutoPrintSetup-{#AppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\AutoPrint.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start AutoPrint when I sign in to Windows (recommended for a shop computer)"; GroupDescription: "Startup:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "{#LicenseDir}\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\AutoPrint"; Filename: "{app}\AutoPrint.exe"
Name: "{autodesktop}\AutoPrint"; Filename: "{app}\AutoPrint.exe"; Tasks: desktopicon

[Registry]
; per-user start at sign-in, in the tray with no window
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AutoPrint"; \
  ValueData: """{app}\AutoPrint.exe"" --background"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\AutoPrint.exe"; Description: "Open AutoPrint now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; stop the running app so its files can be removed. Only the copy installed here: another program on the PC
; can also be called AutoPrint.exe (V3 is), and it must not be stopped.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -Command ""Get-Process AutoPrint -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq '{app}\AutoPrint.exe' } | Stop-Process -Force"""; Flags: runhidden; RunOnceId: "StopAutoPrint"

[UninstallDelete]
; settings, journal and log are kept on purpose (the journal protects against re-printing); remove only temp work files
Type: filesandordirs; Name: "{localappdata}\AutoPrintV4\work"
Type: filesandordirs; Name: "{localappdata}\AutoPrintV4\preview"
