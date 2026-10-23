; Wolverine DS5 installer (Inno Setup 7)
; 先构建 PyInstaller onedir 包（含 wolverine-capture.exe 与 SDL3.dll），再运行：
;   ISCC.exe installer\WolverineDS5.iss

#define AppName "Wolverine DS5"
#define AppVersion "1.0.0"
#define AppPublisher "Winkless213"
#define AppURL "https://github.com/Winkless213/wolverine-ds5"
#define AppExe "WolverineDS5.exe"
#define AppSrc "..\dist\WolverineDS5"

[Setup]
AppId={{7C4F53A6-6B31-4E4C-8E27-19D0B5A62D1F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion=1.0.0.0
VersionInfoDescription={#AppName} installer
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\work\release\installer
OutputBaseFilename=Wolverine-DS5-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE
AllowNoIcons=yes
SetupLogging=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
Source: "{#AppSrc}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\DEVELOPMENT_LOG.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\开发与实测记录"; Filename: "{app}\docs\DEVELOPMENT_LOG.md"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent; Check: ShouldLaunchApp

[Code]
var
  SelfTestPassed: Boolean;

function ShouldLaunchApp: Boolean;
begin
  Result := SelfTestPassed;
end;

function RuntimeFilesPresent: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{app}\{#AppExe}')) and
    FileExists(ExpandConstant('{app}\_internal\wolverine-capture.exe')) and
    FileExists(ExpandConstant('{app}\_internal\SDL3.dll'));
end;

function UsbipPresent: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\USBip\usbip.exe')) or
    FileExists(ExpandConstant('{pf32}\USBip\usbip.exe'));
end;

function HidHidePresent: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\Nefarius Software Solutions\HidHide\x64\HidHideClient.exe')) or
    FileExists(ExpandConstant('{pf32}\Nefarius Software Solutions\HidHide\x86\HidHideClient.exe'));
end;

function SynapsePresent: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{commonprograms}\Razer\Razer Synapse.lnk')) or
    FileExists(ExpandConstant('{commonprograms}\Razer\Razer Synapse 3.lnk')) or
    FileExists(ExpandConstant('{commonprograms}\Razer\Razer Synapse 4.lnk')) or
    FileExists(ExpandConstant('{userprograms}\Razer\Razer Synapse.lnk')) or
    FileExists(ExpandConstant('{userprograms}\Razer\Razer Synapse 3.lnk')) or
    FileExists(ExpandConstant('{userprograms}\Razer\Razer Synapse 4.lnk'));
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if not IsWin64 then
  begin
    MsgBox('Wolverine DS5 需要 64 位 Windows 10 或更高版本。', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Missing: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  if not RuntimeFilesPresent then
  begin
    MsgBox('安装文件不完整：缺少托盘程序、接收程序或 SDL3.dll。' + #13#10 +
           '请重新下载安装包。', mbError, MB_OK);
    Exit;
  end;

  if Exec(ExpandConstant('{app}\{#AppExe}'), '--self-test',
          ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) and
     (ResultCode = 0) then
  begin
    SelfTestPassed := True;
  end
  else
  begin
    MsgBox('安装完成，但启动自检失败。' + #13#10 +
           '请查看 %TEMP%\WolverineDS5-self-test.log，或到 GitHub Issues 反馈。',
           mbError, MB_OK);
  end;

  Missing := '';
  if not UsbipPresent then
    Missing := Missing + '  USBip-win2：https://github.com/vadimgrn/usbip-win2' + #13#10;
  if not HidHidePresent then
    Missing := Missing + '  HidHide：https://github.com/nefarius/HidHide' + #13#10;
  if not SynapsePresent then
    Missing := Missing + '  Razer Synapse：https://www.razer.com/synapse-4' + #13#10;

  if Missing <> '' then
    MsgBox('安装完成。以下外部依赖未检测到，装完暂时不能直接用：' + #13#10#13#10 +
           Missing + #13#10 +
           '装好这些依赖后重新打开 Wolverine DS5；雷云需要保持运行，并在 Chroma 里关闭“音频转震动”。',
           mbInformation, MB_OK);
end;
