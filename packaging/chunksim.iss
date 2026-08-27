; chunksim's Windows installer.
;
; Compile with Inno Setup 6:  iscc packaging\chunksim.iss
; It packages packaging\build\payload, which `build_windows.py` assembles - run
; that first or the compile fails on a missing directory.
;
; Two decisions worth knowing before editing this file:
;
; * AppId is a fixed GUID and MUST NOT change. It is what makes a new version
;   an *upgrade* rather than a second entry in Add/Remove Programs, and what
;   lets the in-app updater hand over to this installer with /SILENT and get a
;   replacement instead of a duplicate.
; * The program installs per-machine, but its data does not live with it.
;   `cache.data_root` puts that under %LOCALAPPDATA%\chunksim, which is right
;   for a per-user cache of someone's own maps and is why uninstalling has to
;   ask about it separately - see the [Code] section at the end.

#define AppName "chunksim"
#define AppVersion "1.0.0"
#define AppPublisher "Steven Hartin"
#define AppURL "https://github.com/stevenhartin/chunksim"
#define Payload "build\payload"

[Setup]
AppId={{7C4B4F2E-9E2D-4E4B-9E7A-2C1F5C9D8A31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; The program is GPL-3.0-or-later. Shipping the terms with the binary is the
; minimum. The *source* ships too, in {app}\source - chunksim is developed in
; public but osrs-dps is not, so pointing at a repository would answer for only
; half of what this installs. See build_windows.bundle_source.
LicenseFile=..\LICENSE
OutputDir=build
; Matches `api.INSTALLER_ASSET_SUFFIX`, which is how the in-app updater finds
; this file among a release's assets. Renaming it here silently turns the
; Download & Install button off.
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 64-bit only: the payload carries the amd64 embeddable interpreter.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Files under Program Files need elevation; the data directory does not, and
; deliberately is not written here.
PrivilegesRequired=admin
; A limpwurt root, cropped from the OSRS Wiki's own item-detail render and
; converted to a multi-resolution icon (CC BY-NC-SA 3.0 - see README.md's
; Credits section). `chunksim.ico` is checked in as a binary; nothing here
; regenerates it from the source render, so replacing the art means
; replacing the file directly.
SetupIconFile=chunksim.ico
UninstallDisplayIcon={app}\chunksim.ico
; Lets the updater replace files this process has open rather than failing on
; a lock. chunksim also stands its own server down before launching us.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "addtopath"; Description: "Add &chunksim to PATH (for the command line)"; GroupDescription: "Command line:"

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; pythonw.exe rather than python.exe: a window opening behind a black console
; is the tell of a Python program pretending to be an application. The
; shortcut's own icon is named separately (`IconFilename`) because a shortcut
; otherwise takes the icon baked into its target, which here is the generic
; embedded-Python interpreter's - not something a user launching "chunksim"
; should be looking for on their desktop.
Name: "{group}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m chunksim.gui"; WorkingDir: "{app}"; IconFilename: "{app}\chunksim.ico"
Name: "{group}\{#AppName} on GitHub"; Filename: "{#AppURL}"; IconFilename: "{app}\chunksim.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m chunksim.gui"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\chunksim.ico"

[Registry]
; PATH gets the install root, where chunksim.cmd is - not the python directory,
; which would put a bare `python.exe` on PATH ahead of the user's own.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m chunksim.gui"; WorkingDir: "{app}"; \
    Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; __pycache__ is written beside the code on first run, so the install tree is
; not exactly what was installed and would otherwise be left behind.
Type: filesandordirs; Name: "{app}\app\chunksim\__pycache__"
Type: filesandordirs; Name: "{app}\app"
Type: dirifempty; Name: "{app}"

[Code]
function NeedsAddPath(Param: string): boolean;
var
  Existing: string;
begin
  { Idempotent: an upgrade must not append the same directory twice. }
  if not RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', Existing) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(Existing) + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  { **Asked, never assumed.** The data directory holds fetched maps, which
    re-download, and simulated batches and hand-edited maps, which do not -
    they are the user's own work and nothing can recompute them. Deleting that
    silently on uninstall would be the single most destructive thing this
    installer could do, so it is a question with "No" as the safe answer. }
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\chunksim');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete your chunksim data?' + #13#10#13#10 +
                DataDir + #13#10#13#10 +
                'This holds your cached maps, simulated runs and edited maps. ' +
                'Fetched maps can be downloaded again; simulations and edits cannot.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
