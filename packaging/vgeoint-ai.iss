; vGeoInt AI add-on: the "ai" Python environment (PyTorch, YOLO, ONNX...) + model weights.
; Installs into the folder of an existing vGeoInt installation. Built by packaging/build.py, which
; passes: AppVersion, PackDir, UnpackExe, ModelsDir, OutputDir.

#define MainAppId "{6B0E3F1C-2D7A-4C59-9E41-6A7F3B1D5C20}"

[Setup]
AppId={{1F4C8A2E-93B5-4E07-8D6C-2B9E5A7C0F31}
AppName=vGeoInt AI
AppVersion={#AppVersion}
AppPublisher=DMA
DefaultDirName={code:MainAppDir}
DisableDirPage=yes
DisableProgramGroupPage=yes
CreateUninstallRegKey=yes
UninstallFilesDir={app}\uninstall-ai
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=vGeoInt-AI-Setup-{#AppVersion}
; Model weights do not compress; 7z/lzma2 still helps the conda packages a little.
Compression=lzma2/fast
SolidCompression=no
; PyTorch with its CUDA libraries makes the add-on larger than one setup .exe can hold (~2.1 GB):
; Setup.exe + Setup-N.bin files, kept together in one folder.
DiskSpanning=yes
DiskSliceSize=max
WizardStyle=modern

[Files]
Source: "{#PackDir}\*"; DestDir: "{app}\pack-ai"; Flags: ignoreversion recursesubdirs createallsubdirs deleteafterinstall
Source: "{#UnpackExe}"; DestDir: "{app}\uninstall-ai"; Flags: ignoreversion
Source: "{#ModelsDir}\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{app}\uninstall-ai\pixi-unpack.exe"; Parameters: """{app}\pack-ai"" --output-directory ""{app}\envs"" --env-name ai --shell cmd"; \
  StatusMsg: "Đang giải nén môi trường AI (vài phút)..."; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/c rmdir /s /q ""{app}\pack-ai"""; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\envs\ai"
Type: files; Name: "{app}\envs\activate.bat"
Type: filesandordirs; Name: "{app}\pack-ai"
Type: dirifempty; Name: "{app}\envs"

[Code]
function MainAppDir(Param: String): String;
var
  Key, Dir: String;
begin
  Result := '';
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MainAppId}_is1';
  if RegQueryStringValue(HKCU, Key, 'InstallLocation', Dir) or
     RegQueryStringValue(HKLM, Key, 'InstallLocation', Dir) then
    Result := RemoveBackslashUnlessRoot(Dir);
end;

function InitializeSetup(): Boolean;
begin
  Result := MainAppDir('') <> '';
  if not Result then
    MsgBox('Chưa cài vGeoInt. Hãy cài vGeoInt-Setup trước rồi mới cài gói AI.', mbError, MB_OK);
end;
