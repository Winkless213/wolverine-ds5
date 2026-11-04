; Wolverine DS5 installer (Inno Setup 7)
; 先构建 PyInstaller onedir 包（含 wolverine-capture.exe 与 SDL3.dll），再运行：
;   ISCC.exe installer\WolverineDS5.iss

#define AppName "Wolverine DS5"
; 版本与源目录可由命令行动态指定：ISCC.exe /DAppVersion=1.1.26 /DAppSrc=..\dist\candidate-1.1.26
#ifndef AppVersion
  #define AppVersion "1.0.4"
#endif
#define AppPublisher "Winkless213"
#define AppURL "https://github.com/Winkless213/wolverine-ds5"
#define AppExe "WolverineDS5.exe"
#ifndef AppSrc
  #define AppSrc "..\dist\WolverineDS5"
#endif
; 随包托盘程序的版本取自 app/__init__.py（WolverineDS5.spec 写入 exe），与 AppVersion 不一致时先重新构建。
#if GetFileProductVersionString(AddBackslash(SourcePath) + AppSrc + "\" + AppExe) != AppVersion
  #error 随包的 WolverineDS5.exe 版本与 AppVersion 不一致，请先重新构建 PyInstaller 包
#endif
; 已装 USBip 低于此版本时提示升级，tools\install-dependencies.ps1 的 $UsbipMinVersion 要保持一致。
#define UsbipMinVersion "0.9.8.0"

[Setup]
AppId={{7C4F53A6-6B31-4E4C-8E27-19D0B5A62D1F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}.0
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
CloseApplications=no
RestartApplications=no
LicenseFile=..\LICENSE
AllowNoIcons=yes
SetupLogging=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

// 老版本把开发文档发给用户，1.1.46 起换成面向用户的使用说明；升级时清掉这些旧文件，免得文档对不上。
[InstallDelete]
Type: files; Name: "{app}\docs\DEVELOPMENT_LOG.md"
Type: files; Name: "{app}\docs\TESTER_GUIDE.md"
Type: files; Name: "{app}\docs\RELEASE_CHECKLIST.md"

[Files]
Source: "{#AppSrc}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\RELEASES.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\tools\install-dependencies.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\tools\uninstall-cleanup.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
// 只给安装器自己用：升级前请旧实例退出，装完不用留在磁盘上。
Source: "..\tools\quit-app.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "..\reference-licenses\*"; DestDir: "{app}\reference-licenses"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\使用说明"; Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\更新记录"; Filename: "{app}\docs\RELEASES.md"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent; Check: ShouldLaunchApp

; 卸载前收尾：放开实体手柄、卸掉虚拟手柄、删除最高权限计划任务（脚本自己提权一次）。
[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\uninstall-cleanup.ps1"" -AppDir ""{app}"""; Flags: runhidden; RunOnceId: "wolverinecleanup"

[Code]
var
  SelfTestPassed: Boolean;
  DepsInstalled: Boolean;

// USBip 和 HidHide 的驱动装完都要重启才生效，完成页据此要求重启。
function NeedRestart: Boolean;
begin
  Result := DepsInstalled;
end;

function ShouldLaunchApp: Boolean;
begin
  // 需要重启时驱动还没生效，启动只会看到一片红；改成重启后由 RunOnce 自动打开并汇报结果。
  Result := SelfTestPassed and not NeedRestart;
end;

// 请运行中的实例自己退出：它会先放开实体手柄、卸掉虚拟手柄，不会再留下两只手柄。
// 直接覆盖运行中的文件会触发 Inno 的“重试/忽略”，忽略就装出半新半旧的目录。
// 注意：旧版（1.1.45 及更早）不认识 --quit，会把它当普通启动，所以必须由脚本核实进程真的没了。
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Exe, Params: String;
  ResultCode: Integer;
begin
  Result := '';
  Exe := ExpandConstant('{app}\{#AppExe}');
  if not FileExists(Exe) then
    Exit;
  ExtractTemporaryFile('quit-app.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\quit-app.ps1') +
            '" -Exe "' + Exe + '"';
  if Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    Exit;
  Result := 'Wolverine DS5 还在运行，没能自动退出。' + #13#10 + #13#10 +
            '请右键点击任务栏右下角的程序图标，选择「退出」，然后回到这里点「下一步」。' + #13#10 +
            '这样它会先把实体手柄还给系统，再安装新版本。';
end;

// 安装不完整时不要把用户放进一个必然打不开的程序里。
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

// 官方安装包会同时注册 usbip2_ude（虚拟主机控制器）和 usbip2_filter（设备过滤驱动）。
// 只装一半时本程序照样能用，但飞智 X-Haptics 这类工具会判「USBIP 驱动不符合要求」，
// 所以这里按完整安装验收，缺哪个都重跑官方安装器修。
function UsbipIncomplete: Boolean;
begin
  Result := UsbipPresent and
    ((not RegKeyExists(HKLM64, 'SYSTEM\CurrentControlSet\Services\usbip2_ude')) or
     (not RegKeyExists(HKLM64, 'SYSTEM\CurrentControlSet\Services\usbip2_filter')));
end;

// 官方说明 0.9.7.8 可能内存损坏导致蓝屏，0.9.8.0 修复并推荐升级；本程序按 0.9.8.0 实测，低于它的都提示升级。
// 版本号取自 usbip.exe（上游安装包的版本号也取自它）；读不到时不拦，按已安装处理。
function UsbipOutdated(var Version: String): Boolean;
var
  Installed, Minimum: Int64;
begin
  Result := False;
  if not GetVersionNumbersString(ExpandConstant('{pf}\USBip\usbip.exe'), Version) then
    Exit;
  if StrToVersion(Version, Installed) and StrToVersion('{#UsbipMinVersion}', Minimum) then
    Result := ComparePackedVersion(Installed, Minimum) < 0;
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

// 缺失或版本过旧的 USBip/HidHide 可在用户确认后自动静默安装并复检；雷云必须登录，只打开下载页。
procedure CheckAndFixDependencies;
var
  Details, Params, ResultFile, UsbipVersion: String;
  S: AnsiString;
  ResultCode: Integer;
begin
  if WizardSilent then
    Exit;

  if (not UsbipPresent) or UsbipOutdated(UsbipVersion) or UsbipIncomplete or (not HidHidePresent) then
  begin
    Details := '';
    if not UsbipPresent then
      Details := Details + #13#10 + '  USBip-win2：未检测到'
    else if UsbipOutdated(UsbipVersion) then
      Details := Details + #13#10 + '  USBip-win2：当前 ' + UsbipVersion +
                 '，需要升级到 {#UsbipMinVersion}（官方推荐版本，修复了 0.9.7.8 的蓝屏问题）'
    else if UsbipIncomplete then
      Details := Details + #13#10 + '  USBip-win2：驱动不完整（缺少 usbip2_ude 或 usbip2_filter），' +
                 '飞智 X-Haptics 等工具会报驱动不符合要求，将重新运行官方安装器修复';
    if not HidHidePresent then
      Details := Details + #13#10 + '  HidHide：未检测到';

    if MsgBox('Wolverine DS5 需要以下系统组件：' + #13#10 + Details +
              '' + #13#10 + #13#10 +
              '是否现在自动安装？需要管理员权限（会弹一次 UAC），安装过程需要联网；' +
              '装好后需要重启一次才能使用。',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      ResultFile := ExpandConstant('{tmp}\WolverineDS5-deps-result.txt');
      DeleteFile(ResultFile);
      Params := '-NoProfile -ExecutionPolicy Bypass -File "' +
                ExpandConstant('{app}\tools\install-dependencies.ps1') + '" -ResultPath "' +
                ResultFile + '" -AutoInstall';
      // UAC 被取消时 ShellExec 返回 False，不会抛异常。
      if ShellExec('runas', 'powershell.exe', Params, '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      begin
        if LoadStringFromFile(ResultFile, S) then
        begin
          DepsInstalled := (StateOf(S, 'usbip') = 'installed') or (StateOf(S, 'hidhide') = 'installed');
          if (StateOf(S, 'usbip') = 'failed') or (StateOf(S, 'hidhide') = 'failed') then
            MsgBox('自动安装未全部成功。请按下面的地址手动安装后重新打开 Wolverine DS5。',
                   mbError, MB_OK)
          else if StateOf(S, 'usbip') = 'incomplete' then
            MsgBox('USBip 驱动仍不完整（缺少 usbip2_ude 或 usbip2_filter）。' + #13#10 +
                   '本程序自身可以工作，但飞智 X-Haptics 等工具会报驱动不符合要求。' + #13#10 +
                   '请重启一次后重新运行安装包；仍不完整就手动重新安装 USBip {#UsbipMinVersion}。',
                   mbInformation, MB_OK);
        end;
      end
      else
        MsgBox('未能以管理员身份启动自动安装（UAC 被取消或提权失败）。' + #13#10 +
               '可以重新运行安装包再选自动安装，或按下面的地址手动安装。', mbInformation, MB_OK);
    end;
  end;

  if (not UsbipPresent) or UsbipOutdated(UsbipVersion) or UsbipIncomplete or (not HidHidePresent) then
  begin
    Details := '';
    if not UsbipPresent then
      Details := Details + '  USBip-win2：https://github.com/vadimgrn/usbip-win2' + #13#10
    else if UsbipOutdated(UsbipVersion) then
      Details := Details + '  USBip-win2 {#UsbipMinVersion}：' +
                 'https://github.com/vadimgrn/usbip-win2/releases/tag/v.{#UsbipMinVersion}' + #13#10
    else if UsbipIncomplete then
      Details := Details + '  USBip-win2 {#UsbipMinVersion}（需重新安装以补全 usbip2_filter）：' +
                 'https://github.com/vadimgrn/usbip-win2/releases/tag/v.{#UsbipMinVersion}' + #13#10;
    if not HidHidePresent then
      Details := Details + '  HidHide：https://github.com/nefarius/HidHide' + #13#10;
    MsgBox('以下组件仍缺失或版本过旧，装好后再打开 Wolverine DS5：' + #13#10#13#10 + Details,
           mbInformation, MB_OK);
  end;

  if not SynapsePresent then
  begin
    if MsgBox('未检测到雷蛇雷云（Razer Synapse）。' + #13#10#13#10 +
              '雷云需要登录账号安装，无法静默完成。现在打开雷云下载页吗？' + #13#10 +
              '装好并保持雷云运行后再打开 Wolverine DS5。雷云的“音频转震动”实测不影响握把，遇到无端震动再关它。',
              mbConfirmation, MB_YESNO) = IDYES then
      OpenSynapseDownloadPage;
  end;
end;

// 需要重启时：重启后自动打开程序，并让它在第一次自检后主动汇报结果。
procedure QueueFirstRun;
begin
  if (not SelfTestPassed) or (not NeedRestart) then
    Exit;
  SaveStringToFile(ExpandConstant('{app}\first-run.pending'), '1', False);
  RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce',
    'WolverineDS5FirstRun', '"' + ExpandConstant('{app}\{#AppExe}') + '"');
end;

function InitializeSetup: Boolean;begin
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
  QueueFirstRun;
end;
