$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $projectRoot '.runtime/web.pid'
$pythonPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot '.venv/Scripts/python.exe'))

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Output 'No background server was recorded.'
    return
}

$serverProcessId = [int](Get-Content -LiteralPath $pidPath)
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $serverProcessId"
if (-not $serverProcess) {
    Write-Output 'The recorded server is already stopped.'
    return
}

if ($serverProcess.ExecutablePath -ine $pythonPath -or
    $serverProcess.CommandLine -notmatch 'uvicorn\s+app\.main:app') {
    throw 'The recorded process no longer matches this project. No process was stopped.'
}

Stop-Process -Id $serverProcessId
Remove-Item -LiteralPath $pidPath
Write-Output 'VPS Rent stopped. PostgreSQL data is preserved.'
