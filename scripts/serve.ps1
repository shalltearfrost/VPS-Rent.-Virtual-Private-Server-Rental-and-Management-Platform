param([switch]$Background)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create the virtual environment and install dependencies first. See README.md.'
}

if ($Background) {
    $runtimePath = Join-Path $projectRoot '.runtime'
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    $serverProcess = Start-Process -FilePath $pythonPath `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimePath 'web.stdout.log') `
        -RedirectStandardError (Join-Path $runtimePath 'web.stderr.log')
    $serverProcess.Id | Set-Content -LiteralPath (Join-Path $runtimePath 'web.pid')
    Write-Output 'VPS Rent is starting at http://127.0.0.1:8000. Stop with scripts/stop.ps1.'
} else {
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
