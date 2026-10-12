param(
    [ValidateSet('check', 'pipeline', 'synthetic', 'capture', 'bridge')][string]$Mode = 'check',
    [ValidateRange(1, 300)][int]$Seconds = 60,
    [switch]$SensaPreview,
    [ValidateSet(250, 1000)][int]$InputPollHz = 1000
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    $runtime = (Get-Command python -ErrorAction Stop).Source
}
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($Mode -eq 'check') {
        & $runtime -X utf8 -m unittest discover -v
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
        & $runtime -X utf8 api_check.py
        if ($LASTEXITCODE -ne 0) { throw 'USB/IP check failed' }
        & $runtime -X utf8 sensa_api_check.py
        if ($LASTEXITCODE -ne 0) { throw 'Sensa offline check failed' }
    } elseif ($Mode -eq 'pipeline') {
        & $runtime -X utf8 sensa_stream_check.py
        if ($LASTEXITCODE -ne 0) { throw 'Continuous Sensa check failed' }
        & $runtime -X utf8 sensa_mapping_check.py
        if ($LASTEXITCODE -ne 0) { throw 'Sensa mapping characterization failed' }
    } else {
        $captureArgs = @('-X', 'utf8', 'run_capture.py', '--seconds', "$Seconds", '--input-poll-hz', "$InputPollHz")
        if ($Mode -eq 'synthetic') { $captureArgs += '--synthetic' }
        if ($Mode -eq 'bridge') { $captureArgs += '--xusb-output' }
        if ($SensaPreview) { $captureArgs += '--sensa-preview' }
        & $runtime @captureArgs
        if ($LASTEXITCODE -ne 0) { throw 'Capture failed; inspect runs/*/run.json' }
    }
} finally {
    Pop-Location
}
