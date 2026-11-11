[Setup]
#ifdef TestInstall
AppId=PhotoProfiler.InstallTest.v1
#else
AppId={{143B61FC-BAB7-4DD4-8A74-78B429D60177}
#endif
AppName=Photo Profiler
AppVersion=1.13
AppVerName=Photo Profiler 1.13
VersionInfoVersion=1.13.0.0
DefaultDirName={localappdata}\Programs\Photo Profiler
DefaultGroupName=Photo Profiler
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Photo Profiler.exe
UninstallDisplayName=Photo Profiler
OutputDir=dist
OutputBaseFilename=Photo Profiler Setup 1.13
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "build\update\PhotoProfilerUpdate.exe"; Flags: dontcopy
Source: "dist\Photo Profiler\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

#ifndef TestInstall
[Icons]
Name: "{userprograms}\Photo Profiler"; Filename: "{app}\Photo Profiler.exe"
Name: "{userdesktop}\Photo Profiler"; Filename: "{app}\Photo Profiler.exe"; Tasks: desktopicon
#endif

[Run]
Filename: "{app}\Photo Profiler.exe"; Description: "Open Photo Profiler"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  AppPath: String;
begin
  Result := '';
  AppPath := ExpandConstant('{app}\Photo Profiler.exe');
  if FileExists(AppPath) then
  begin
    WizardForm.StatusLabel.Caption := 'Closing Photo Profiler...';
    ExtractTemporaryFile('PhotoProfilerUpdate.exe');
    if not Exec(ExpandConstant('{tmp}\PhotoProfilerUpdate.exe'), '"' + AppPath + '"',
                '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'Photo Profiler could not be closed. Close it and try again.'
    else if ExitCode <> 0 then
      Result := 'Photo Profiler is still in use. Close it and try again.';
  end;
end;
