; vGeoInt main installer: the three apps + the QGIS runtime environment.
; Built by packaging/build.py, which passes: AppVersion, StageDir, PackDir, UnpackExe, OutputDir.

#define AppName "vGeoInt"
#define MainAppId "{{6B0E3F1C-2D7A-4C59-9E41-6A7F3B1D5C20}"

[Setup]
AppId={#MainAppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DMA
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=vGeoInt-Setup-{#AppVersion}
SetupIconFile={#StageDir}\resources\vGeoInt.ico
UninstallDisplayIcon={app}\resources\vGeoInt.ico
Compression=lzma2/max
SolidCompression=no
DiskSpanning=no
WizardStyle=modern

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PackDir}\*"; DestDir: "{app}\pack"; Flags: ignoreversion recursesubdirs createallsubdirs deleteafterinstall
Source: "{#UnpackExe}"; DestDir: "{app}\tools"; Flags: ignoreversion

[Run]
Filename: "{app}\tools\pixi-unpack.exe"; Parameters: """{app}\pack"" --output-directory ""{app}"" --env-name env --shell cmd"; \
  StatusMsg: "Đang giải nén môi trường QGIS (vài phút)..."; Flags: runhidden waituntilterminated
Filename: "{app}\env\python.exe"; Parameters: """{app}\make_launch_env.py"" ""{app}"""; \
  StatusMsg: "Đang cấu hình..."; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/c rmdir /s /q ""{app}\pack"""; Flags: runhidden waituntilterminated
Filename: "{app}\env\pythonw.exe"; Parameters: """{app}\launcher.pyw"" vgeoint.app"; WorkingDir: "{app}"; \
  Description: "Chạy vGeoInt"; Flags: postinstall nowait skipifsilent

[Icons]
Name: "{group}\vGeoInt"; Filename: "{app}\env\pythonw.exe"; Parameters: """{app}\launcher.pyw"" vgeoint.app"; WorkingDir: "{app}"; IconFilename: "{app}\resources\vGeoInt.ico"
Name: "{group}\vGeoCatalog"; Filename: "{app}\env\pythonw.exe"; Parameters: """{app}\launcher.pyw"" vgeoint.catalog"; WorkingDir: "{app}"; IconFilename: "{app}\resources\vGeoCatalog.ico"
Name: "{group}\vGeoEngine"; Filename: "{app}\env\pythonw.exe"; Parameters: """{app}\launcher.pyw"" vgeoint.engine"; WorkingDir: "{app}"; IconFilename: "{app}\resources\vGeoEngine.ico"
Name: "{group}\Gỡ cài đặt vGeoInt"; Filename: "{uninstallexe}"
Name: "{autodesktop}\vGeoInt"; Filename: "{app}\env\pythonw.exe"; Parameters: """{app}\launcher.pyw"" vgeoint.app"; WorkingDir: "{app}"; IconFilename: "{app}\resources\vGeoInt.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng trên Desktop"; Flags: unchecked

[UninstallDelete]
; Created at install time by pixi-unpack / make_launch_env.py, and at run time (logs, caches).
Type: filesandordirs; Name: "{app}\env"
Type: filesandordirs; Name: "{app}\pack"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\src"
Type: files; Name: "{app}\activate.bat"
Type: files; Name: "{app}\launch_env.json"
Type: dirifempty; Name: "{app}\envs"
Type: dirifempty; Name: "{app}"
