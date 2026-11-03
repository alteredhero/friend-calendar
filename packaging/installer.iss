; Friend Calendar installer. Built by packaging\build.py (it passes AppVersion, SourceDir, output dir).
; Per-user install: no admin prompt. Program files go to %LOCALAPPDATA%\Programs\Friend Calendar,
; your calendar's data lives separately in %LOCALAPPDATA%\FriendCalendar and survives upgrades
; and uninstalls.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\dist\FriendCalendar"
#endif

#define AppName "Friend Calendar"
#define AppExe "FriendCalendar.exe"
#define DataDir "{localappdata}\FriendCalendar"

[Setup]
AppId={{6C3D57F1-DE80-40D1-A134-BFC2A0D7CC1E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=alteredhero
AppPublisherURL=https://github.com/alteredhero/friend-calendar
AppSupportURL=https://github.com/alteredhero/friend-calendar/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=FriendCalendar-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
InfoBeforeFile=disclaimer.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
DisableProgramGroupPage=yes

[Tasks]
Name: "autostart"; Description: "Start Friend Calendar when I sign in to Windows"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same key and value the app itself uses for its "Start at login" menu item.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "FriendCalendar"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; 1. optional: restore a backup the user picked on the "Restore" page
Filename: "{app}\{#AppExe}"; Parameters: "--import-backup ""{code:BackupPath}"""; \
  Flags: runhidden waituntilterminated; Check: HaveBackup; StatusMsg: "Restoring your backup..."
; 2. no password yet (fresh install, and none came from the backup): ask for one
Filename: "{app}\{#AppExe}"; Parameters: "--set-password"; \
  Flags: waituntilterminated; Check: NeedsPassword; Description: "Choose a group password"
; 3. start the calendar
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExe}"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
var
  BackupPage: TInputFileWizardPage;

procedure InitializeWizard;
begin
  BackupPage := CreateInputFilePage(wpSelectTasks,
    'Restore a backup (optional)',
    'Moving from another PC or reinstalling?',
    'If you have a backup zip made by Friend Calendar ("Back up data..." in the tray menu, ' +
    'or backup.py), choose it to bring your events, users and password along. ' +
    'Otherwise just leave this empty and click Next.');
  BackupPage.Add('Backup file (.zip):', 'Zip files|*.zip|All files|*.*', '.zip');
end;

function BackupPath(Param: String): String;
begin
  Result := BackupPage.Values[0];
end;

function HaveBackup: Boolean;
begin
  Result := BackupPage.Values[0] <> '';
end;

function NeedsPassword: Boolean;
begin
  Result := (not WizardSilent) and (not FileExists(ExpandConstant('{#DataDir}\auth.json')));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if not UninstallSilent then
      MsgBox('Friend Calendar was removed, but your calendar data was kept in:' + #13#10 +
             ExpandConstant('{#DataDir}') + #13#10#13#10 +
             'Delete that folder if you want to erase your events and password too.',
             mbInformation, MB_OK);
end;
