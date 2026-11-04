# Ask a running Wolverine DS5 instance to quit before files are replaced.
# Called by the installer with -Exe pointing at the already-installed exe.
# Exit 0 when no instance is running, 1 when it is still alive after the wait.
param([string]$Exe = '')

$ErrorActionPreference = 'Continue'

function Get-App {
    Get-Process -Name 'WolverineDS5' -ErrorAction SilentlyContinue
}

if (-not (Get-App)) { exit 0 }

# 1.1.46 and later understand --quit and restore the physical pad before exiting.
# Older builds ignore the switch and just show their window, so always verify the process is gone.
if ($Exe -and (Test-Path -LiteralPath $Exe)) {
    try { Start-Process -FilePath $Exe -ArgumentList '--quit' -Wait -PassThru | Out-Null } catch { }
}

for ($i = 0; $i -lt 40; $i++) {
    if (-not (Get-App)) { exit 0 }
    Start-Sleep -Milliseconds 500
}
exit 1
