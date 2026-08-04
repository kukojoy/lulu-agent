$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendHost = if ($env:LULU_BACKEND_HOST) { $env:LULU_BACKEND_HOST } else { "127.0.0.1" }
$BackendPort = if ($env:LULU_BACKEND_PORT) { $env:LULU_BACKEND_PORT } else { "8000" }
$FrontendPort = if ($env:LULU_FRONTEND_PORT) { $env:LULU_FRONTEND_PORT } else { "5173" }
$CondaEnv = if ($env:LULU_CONDA_ENV) { $env:LULU_CONDA_ENV } else { "lulu-agent" }

Set-Location $RootDir

function Test-Command($Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if ($env:LULU_PYTHON) {
  $PythonExe = $env:LULU_PYTHON
  $PythonArgs = @()
} elseif (Test-Command "python") {
  $PythonExe = "python"
  $PythonArgs = @()
} elseif (Test-Command "conda") {
  $PythonExe = "conda"
  $PythonArgs = @("run", "--no-capture-output", "-n", $CondaEnv, "python")
} else {
  Write-Error "python or conda is required to start lulu-agent."
}

if (-not (Test-Command "npm")) {
  Write-Error "npm is required to start the lulu-agent GUI."
}

if (-not (Test-Path (Join-Path $RootDir "gui\node_modules"))) {
  Write-Error "gui\node_modules is missing. Run: cd gui && npm install"
}

$BackendArgs = $PythonArgs + @(
  "-m",
  "uvicorn",
  "lulu_agent.server.app:app",
  "--host",
  $BackendHost,
  "--port",
  $BackendPort
)

$FrontendArgs = @(
  "run",
  "dev",
  "--prefix",
  "gui",
  "--",
  "--port",
  $FrontendPort,
  "--strictPort"
)

Write-Host "Starting lulu-agent backend: http://${BackendHost}:${BackendPort}"
$Backend = Start-Process -FilePath $PythonExe -ArgumentList $BackendArgs -WorkingDirectory $RootDir -PassThru -NoNewWindow

Write-Host "Starting lulu-agent GUI: http://127.0.0.1:${FrontendPort}"
$Frontend = Start-Process -FilePath "npm" -ArgumentList $FrontendArgs -WorkingDirectory $RootDir -PassThru -NoNewWindow

$Url = "http://127.0.0.1:${FrontendPort}"
Write-Host "lulu-agent GUI is starting."
Write-Host "Open: $Url"
Write-Host "Press Ctrl+C to stop both processes."

Start-Sleep -Seconds 2
Start-Process $Url | Out-Null

try {
  while (-not $Backend.HasExited -and -not $Frontend.HasExited) {
    Start-Sleep -Seconds 1
    $Backend.Refresh()
    $Frontend.Refresh()
  }

  if ($Backend.HasExited) {
    Write-Host "Backend exited with code $($Backend.ExitCode)."
  }
  if ($Frontend.HasExited) {
    Write-Host "GUI exited with code $($Frontend.ExitCode)."
  }
} finally {
  if ($Backend -and -not $Backend.HasExited) {
    Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
  }
  if ($Frontend -and -not $Frontend.HasExited) {
    Stop-Process -Id $Frontend.Id -Force -ErrorAction SilentlyContinue
  }
}
