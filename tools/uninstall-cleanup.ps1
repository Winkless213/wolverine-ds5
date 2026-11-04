# 卸载收尾：放开实体手柄、卸掉虚拟手柄、删除最高权限计划任务。
# 由安装器的卸载流程调用；也能手动运行：powershell -ExecutionPolicy Bypass -File tools\uninstall-cleanup.ps1 -AppDir "C:\...\Wolverine DS5"
# HidHide 和设备操作都需要管理员，所以这里自己再提权一次，用户取消就安静退出。

param([string]$AppDir = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Continue'
$logPath = Join-Path $env:TEMP 'WolverineDS5-uninstall.log'

function Write-Log {
    param([string]$Message)
    Add-Content -LiteralPath $logPath -Value ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message) -Encoding UTF8
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Log 'not elevated, relaunching with consent'
    # 路径里带空格，参数必须拼成一个带引号的字符串再传，不能交数组给 -ArgumentList。
    $inner = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -AppDir "{1}"' -f $PSCommandPath, $AppDir
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList $inner
    }
    catch {
        # 用户取消提权：收尾没做，必须明确告诉他，不能悄悄继续卸载。
        Write-Log "elevation cancelled: $_"
        $message = '没有获得管理员授权，卸载前的收尾未执行：' + "`r`n" +
                   '实体手柄可能仍被隐藏、虚拟手柄可能仍在挂载、计划任务可能仍在。' + "`r`n`r`n" +
                   '程序文件会被删除；如需彻底清理，请重启电脑后重新运行本安装包并选择卸载，' + "`r`n" +
                   '或在“任务计划程序”删除 WolverineDS5-RazerSynapse，在 HidHide 客户端取消隐藏。' + "`r`n`r`n" +
                   '注意：不要手动删除 USBIP 驱动或服务，那可能破坏 USB 层。'
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.MessageBox]::Show($message, 'Wolverine DS5 卸载收尾未执行',
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
        }
        catch {
            Write-Log "messagebox failed: $_"
        }
        exit 2
    }
    exit 0
}

# 不依赖 WolverineDS5.exe 的最小收尾：exe 被删/损坏/依赖坏掉时也要能把系统还原。
# 仍然只做三件事，绝不删除 USBIP 驱动、服务或驱动包。
function Invoke-FallbackCleanup {
    Write-Log 'exe cleanup unavailable, running fallback'
    $usbip = Join-Path $env:ProgramFiles 'USBip\usbip.exe'
    if (Test-Path -LiteralPath $usbip) {
        $ports = (& $usbip port 2>&1) -join "`n"
        foreach ($match in [regex]::Matches($ports, '(?m)^Port\s+(\d+):')) {
            $port = $match.Groups[1].Value
            Write-Log "detach port $port"
            (& $usbip detach -p $port 2>&1) | ForEach-Object { Write-Log "  $_" }
        }
    }
    else {
        Write-Log 'usbip.exe missing; 跳过挂载解除（不要手动删 USBIP 驱动）'
    }
    $hidhide = Join-Path $env:ProgramFiles 'Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe'
    if (Test-Path -LiteralPath $hidhide) {
        $instances = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
            Where-Object { $_.InstanceId -match 'VID_1532&PID_0A4C' } |
            Select-Object -ExpandProperty InstanceId
        foreach ($instance in $instances) {
            Write-Log "unhide $instance"
            (& $hidhide --dev-unhide $instance 2>&1) | ForEach-Object { Write-Log "  $_" }
        }
        $bridge = Join-Path $AppDir 'WolverineDS5-bridge.exe'
        (& $hidhide --app-unreg $bridge 2>&1) | ForEach-Object { Write-Log "  $_" }
        Write-Log 'note: 只解除本程序手柄的隐藏与放行，不改动其它设备的隐藏名单'
    }
    (& schtasks.exe /delete /tn 'WolverineDS5-RazerSynapse' /f 2>&1) | ForEach-Object { Write-Log "  $_" }
    Remove-ItemProperty -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -Name 'WolverineDS5' -ErrorAction SilentlyContinue
    Write-Log 'fallback cleanup done'
}

$exe = Join-Path $AppDir 'WolverineDS5.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Log "app exe missing: $exe"
    Invoke-FallbackCleanup
    exit 0
}

# 卸载的安全边界：只解除虚拟手柄挂载、恢复实体手柄、删本程序的计划任务。
# 绝不删除 USBIP 驱动/服务/驱动包——删了可能破坏 USB 层（实测有用户因此只能重装系统）。
function Get-UsbipState {
    $state = foreach ($name in 'usbip2_ude', 'usbip2_filter') {
        $service = Get-Service -Name $name -ErrorAction SilentlyContinue
        '{0}={1}' -f $name, ($(if ($service) { [string]$service.Status } else { 'missing' }))
    }
    return ($state -join ',')
}

$usbipBefore = Get-UsbipState
Write-Log "usbip services before: $usbipBefore"

# 先请运行中的实例自己退出：它会放开实体手柄、卸掉虚拟手柄；强杀会跳过这一步。
if (Get-Process -Name 'WolverineDS5' -ErrorAction SilentlyContinue) {
    $quit = Start-Process -FilePath $exe -ArgumentList '--quit' -Wait -PassThru
    Write-Log ('--quit exit={0}' -f $quit.ExitCode)
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Process -Name 'WolverineDS5' -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
}

# 兜底：还没退出就强杀；后面的 --uninstall 仍会补做原生恢复。
Get-Process -Name 'WolverineDS5', 'WolverineDS5-bridge', 'wolverine-capture' -ErrorAction SilentlyContinue |
    Stop-Process -Force
Start-Sleep -Seconds 2

# 窗口版 exe 没有控制台：等它退出，退出码写日志；细节在 %TEMP%\WolverineDS5-uninstall-result.txt。
$resultFile = Join-Path $env:TEMP 'WolverineDS5-uninstall-result.txt'
Remove-Item -LiteralPath $resultFile -Force -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath $exe -ArgumentList '--uninstall' -Wait -PassThru
Write-Log ('--uninstall exit={0}' -f $proc.ExitCode)
$resultOk = $false
if (Test-Path -LiteralPath $resultFile) {
    $resultText = (Get-Content -LiteralPath $resultFile -Encoding UTF8) -join ' / '
    Write-Log ('result file: ' + $resultText)
    $resultOk = $resultText -match 'result=ok'
}
if ($proc.ExitCode -ne 0 -or -not $resultOk) {
    Write-Log 'exe cleanup incomplete, running fallback'
    Invoke-FallbackCleanup
}

$usbipAfter = Get-UsbipState
Write-Log "usbip services after: $usbipAfter"
if ($usbipBefore -ne $usbipAfter) {
    Write-Log 'WARNING: usbip 服务状态在卸载过程中变了，请检查设备管理器与 USB 设备'
}
Write-Log 'note: 卸载不删除 USBIP 驱动、服务或驱动包；USBIP 由官方安装器自行管理'
exit 0