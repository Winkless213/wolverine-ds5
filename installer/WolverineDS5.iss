; Wolverine DS5 installer (Inno Setup 7)
; 先构建 PyInstaller onedir 包（含 wolverine-capture.exe 与 SDL3.dll），再运行：
;   ISCC.exe installer\WolverineDS5.iss

#define AppName "Wolverine DS5"
#define AppVersion "1.0.2"
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
VersionInfoVersion=1.0.2.0
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
Source: "..\tools\install-dependencies.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\reference-licenses\*"; DestDir: "{app}\reference-licenses"; Flags: ignoreversion

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

function StateOf(S: AnsiString; Key: String): String;
var
  P, Q: Integer;
begin
  Result := '';
  P := Pos(Key + '=', S);
  if P = 0 then
    Exit;
  P := P + Length(Key) + 1;
  Q := P;
  while (Q <= Length(S)) and (S[Q] <> #13) and (S[Q] <> #10) do
    Q := Q + 1;
  Result := Copy(S, P, Q - P);
end;

procedure OpenSynapseDownloadPage;
var
  ResultCode: Integer;
begin
  ShellExec('', 'https://www.razer.com/synapse-4', '', '', SW_SHOW, ewNoWait, ResultCode);
end;

// 缺失的 USBip/HidHide 可在用户确认后自动静默安装并复检；雷云必须登录，只打开下载页。
procedure CheckAndFixDependencies;
var
  Details, Params, ResultFile: String;
  S: AnsiString;
  ResultCode: Integer;
begin
  if WizardSilent then
    Exit;

  if (not UsbipPresent) or (not HidHidePresent) then
  begin
    Details := '';
    if not UsbipPresent then
      Details := Details + #13#10 + '  USBip-win2';
    if not HidHidePresent then
      Details := Details + #13#10 + '  HidHide';

    if MsgBox('Wolverine DS5 需要以下系统组件，当前未检测到：' + #13#10 + Details +
              '' + #13#10 + #13#10 +
              '是否现在自动安装？需要管理员权限（会弹一次 UAC），安装过程需要联网；' +
              'HidHide 装好后可能需要重启一次。',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      ResultFile := ExpandConstant('{tmp}\WolverineDS5-deps-result.txt');
      DeleteFile(ResultFile);
      Params := '-NoProfile -ExecutionPolicy Bypass -File "' +
                ExpandConstant('{app}\tools\install-dependencies.ps1') + '" -ResultPath "' +
                ResultFile + '" -AutoInstall';
      try
        if ShellExec('runas', 'powershell.exe', Params, '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          if LoadStringFromFile(ResultFile, S) then
          begin
            if (StateOf(S, 'usbip') = 'failed') or (StateOf(S, 'hidhide') = 'failed') then
              MsgBox('自动安装未全部成功。请按下面的地址手动安装后重新打开 Wolverine DS5。',
                     mbError, MB_OK);
          end;
        end;
      except
        MsgBox('未能以管理员身份启动自动安装（UAC 被取消或提权失败）。' + #13#10 +
               '可以右键以管理员身份运行安装目录下的 tools\install-dependencies.ps1，' +
               '或按下面的地址手动安装。', mbInformation, MB_OK);
      end;
    end;
  end;

  if (not UsbipPresent) or (not HidHidePresent) then
  begin
    Details := '';
    if not UsbipPresent then
      Details := Details + '  USBip-win2：https://github.com/vadimgrn/usbip-win2' + #13#10;
    if not HidHidePresent then
      Details := Details + '  HidHide：https://github.com/nefarius/HidHide' + #13#10;
    MsgBox('以下组件仍缺失，装好后再打开 Wolverine DS5：' + #13#10#13#10 + Details,
           mbInformation, MB_OK);
  end;

  if not SynapsePresent then
  begin
    if MsgBox('未检测到雷蛇雷云（Razer Synapse）。' + #13#10#13#10 +
              '雷云需要登录账号安装，无法静默完成。现在打开雷云下载页吗？' + #13#10 +
              '装好并保持雷云运行后再打开 Wolverine DS5，并在 Chroma 里关闭“音频转震动”。',
              mbConfirmation, MB_YESNO) = IDYES then
      OpenSynapseDownloadPage;
  end;
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

  CheckAndFixDependencies;
end;
