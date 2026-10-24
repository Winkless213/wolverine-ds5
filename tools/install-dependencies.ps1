# Wolverine DS5 外部依赖自动安装脚本。
# 由安装器在用户确认后以管理员身份调用，也可手动运行：
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install-dependencies.ps1 -AutoInstall
# 结果写成 ASCII 键值行（usbip=installed 等），安装器直接读取显示。

param(
    [string]$ResultPath = (Join-Path $env:TEMP 'WolverineDS5-deps-result.txt'),
    [switch]$AutoInstall,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$logPath = Join-Path $env:TEMP 'WolverineDS5-deps.log'
# 安装器拉起的是 32 位 PowerShell，$env:ProgramFiles 会指向 Program Files (x86)。
$programFiles = if ($env:ProgramW6432) { $env:ProgramW6432 } else { $env:ProgramFiles }

function Write-Log {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

# 固定为实测过的官方安装包并校验哈希，升级依赖时同步更新这里。
# 不用 winget：它只提供 USBip 0.9.7.8，官方说明该版本有内存损坏和蓝屏问题，0.9.8.0 修复。
$Usbip = @{
    Url    = 'https://github.com/vadimgrn/usbip-win2/releases/download/v.0.9.8.0/USBip-0.9.8.0-x64.exe'
    Sha256 = '81f426741f7ee2ed991febe24a22daca8400b6ae2f171054e3fb404897e15d39'
    Args   = '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
}
$HidHide = @{
    Url    = 'https://github.com/nefarius/HidHide/releases/download/v1.5.230.0/HidHide_1.5.230_x64.exe'
    Sha256 = 'f4bbbcb82e6258641b887c74bc81c4c5f66e4aa811808dfc304347687b7605f6'
    Args   = '/exenoui', '/qn', '/norestart'
}

function Test-Usbip {
    if (Test-Path -LiteralPath (Join-Path $programFiles 'USBip\usbip.exe')) { return $true }
    return [bool](Get-Service -Name 'usbip2_ude' -ErrorAction SilentlyContinue)
}

function Test-HidHide {
    if (Test-Path -LiteralPath (Join-Path $programFiles 'Nefarius Software Solutions\HidHide\x64\HidHideClient.exe')) { return $true }
    return [bool](Get-Service -Name 'HidHide' -ErrorAction SilentlyContinue)
}

function Test-Synapse {
    $links = @(
        (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Razer\Razer Synapse.lnk'),
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Razer\Razer Synapse.lnk')
    )
    foreach ($link in $links) {
        if (Test-Path -LiteralPath $link) { return $true }
    }
    return Test-Path -LiteralPath (Join-Path $programFiles 'Razer\RazerAppEngine\RazerAppEngine.exe')
}

function Invoke-DownloadInstall {
    param($Spec, [string]$Name)
    $file = Join-Path $env:TEMP ([IO.Path]::GetFileName(([Uri]$Spec.Url).AbsolutePath))
    Write-Log "download $($Spec.Url)"
    Invoke-WebRequest -Uri $Spec.Url -OutFile $file -UseBasicParsing
    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $Spec.Sha256) {
        throw "$Name 安装包哈希不匹配：$hash"
    }
    $proc = Start-Process -FilePath $file -ArgumentList $Spec.Args -Wait -PassThru
    Write-Log "$Name installer exit=$($proc.ExitCode)"
}

function Install-Dependency {
    param($Spec, [string]$Name, [scriptblock]$Check)
    if (& $Check) {
        Write-Log "$Name already present"
        return 'present'
    }
    if (-not $AutoInstall) {
        Write-Log "$Name missing, install not requested"
        return 'missing'
    }
    try {
        Invoke-DownloadInstall -Spec $Spec -Name $Name
    }
    catch {
        Write-Log "$Name install error: $_"
    }
    Start-Sleep -Seconds 3
    if (& $Check) {
        Write-Log "$Name installed"
        return 'installed'
    }
    Write-Log "$Name still missing after install"
    return 'failed'
}

# 雷云只做检测：官方是联网引导安装器，必须登录，无法无人值守完成。
function Get-SynapseResult {
    if (Test-Synapse) { return 'present' }
    return 'manual'
}

$lines = New-Object System.Collections.Generic.List[string]

if (-not $CheckOnly -and $AutoInstall) {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Log 'not elevated, cannot install dependencies'
        $lines.Add('error=elevation')
        $lines -join "`r`n" | Out-File -LiteralPath $ResultPath -Encoding ASCII
        exit 4
    }
}

$lines.Add('usbip=' + (Install-Dependency -Spec $Usbip -Name 'USBip-win2' -Check ${function:Test-Usbip}))
$lines.Add('hidhide=' + (Install-Dependency -Spec $HidHide -Name 'HidHide' -Check ${function:Test-HidHide}))

$lines.Add('synapse=' + (Get-SynapseResult))

$lines -join "`r`n" | Out-File -LiteralPath $ResultPath -Encoding ASCII
Write-Log ('result: ' + ($lines -join ', '))

$failed = $lines | Where-Object { $_ -match '=(failed|missing)$' }
if ($failed) { exit 2 }
exit 0
