param([switch]$Restart)

$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workspacePath '.venv\Scripts\python.exe'
$runtimePath = Join-Path $workspacePath '.runtime'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
if ($Restart) {
    $pidPath = Join-Path $runtimePath 'uvicorn.pid'
    if (-not (Test-Path -LiteralPath $pidPath)) {
        throw 'No managed Uvicorn PID file exists.'
    }
    $managedProcessId = [int](Get-Content -LiteralPath $pidPath)
    $managedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $managedProcessId"
    if ($managedProcess) {
        if ($managedProcess.ExecutablePath -notlike "$workspacePath\*" -or $managedProcess.CommandLine -notmatch 'uvicorn app\.main:app') {
            throw 'The saved PID does not identify this workspace Uvicorn process.'
        }
        taskkill.exe /PID $managedProcessId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to stop the managed Uvicorn process.' }
    }
}
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is already occupied. Verify the existing process before restarting it.'
}
$env:EDGAR_LOCAL_DATA_DIR = Join-Path $workspacePath '.edgar'
$serverProcess = Start-Process -FilePath $pythonPath -WindowStyle Hidden -WorkingDirectory $workspacePath `
    -ArgumentList '-m uvicorn app.main:app --host 0.0.0.0 --port 8000' `
    -RedirectStandardOutput (Join-Path $runtimePath 'uvicorn.stdout.log') `
    -RedirectStandardError (Join-Path $runtimePath 'uvicorn.stderr.log') -PassThru
$serverProcess.Id | Set-Content -LiteralPath (Join-Path $runtimePath 'uvicorn.pid')
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        throw 'Uvicorn exited. Inspect .runtime/uvicorn.stderr.log.'
    }
    try {
        $healthResult = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3
        Write-Output "Uvicorn running on 0.0.0.0:8000, launcher PID $($serverProcess.Id), pgvector $($healthResult.pgvector_version)"
        exit 0
    } catch {
        Start-Sleep -Seconds 1
    }
}
throw 'Uvicorn health check did not succeed within 60 seconds.'
