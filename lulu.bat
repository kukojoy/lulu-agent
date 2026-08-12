@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem 获取工作目录
set "WORKSPACE_DIR=%CD%"

rem 获取项目目录 (启动脚本的根目录)
set "ROOT_DIR=%~dp0"
set "ROOT_DIR=%ROOT_DIR:~0,-1%"

rem 端口配置
set "BACKEND_HOST=127.0.0.1"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

cd /d "%ROOT_DIR%" || exit /b 1

rem 检查 python 命令
for /f "delims=" %%I in ('where python.exe 2^>nul') do (
  set "PYTHON_EXE=%%I"
  goto :python_found
)
echo python is required to start lulu-agent. Activate the expected environment first. 1>&2
exit /b 1

:python_found

rem 检查 npm 命令
for /f "delims=" %%I in ('where npm.cmd 2^>nul') do (
  set "NPM_EXE=%%I"
  goto :npm_found
)
echo npm is required to start the lulu-agent GUI. 1>&2
exit /b 1

:npm_found

rem 检查 PowerShell 命令
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo PowerShell is required to start the lulu-agent GUI. 1>&2
  exit /b 1
)

rem 检查前端依赖
if not exist "%ROOT_DIR%\gui\node_modules" (
  echo gui\node_modules is missing. Run: cd gui ^&^& npm install 1>&2
  exit /b 1
)

set "BACKEND_PID="
set "FRONTEND_PID="

call :find_available_port BACKEND_PORT %BACKEND_PORT%
if "%BACKEND_PORT%"=="" (
  echo No available backend port found. 1>&2
  exit /b 1
)

call :find_available_port FRONTEND_PORT %FRONTEND_PORT%
if "%FRONTEND_PORT%"=="" (
  echo No available frontend port found. 1>&2
  exit /b 1
)

call :run
set "EXIT_CODE=%ERRORLEVEL%"
call :cleanup
exit /b %EXIT_CODE%

:run
rem 开启后端
echo Starting lulu-agent backend: http://%BACKEND_HOST%:%BACKEND_PORT%
if defined PYTHONPATH (
  set "_BACKEND_PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%"
) else (
  set "_BACKEND_PYTHONPATH=%ROOT_DIR%"
)
call :start_process BACKEND_PID "%PYTHON_EXE%" "-m uvicorn lulu_agent.server.app:app --host %BACKEND_HOST% --port %BACKEND_PORT%" "%WORKSPACE_DIR%" "PYTHONPATH" "%_BACKEND_PYTHONPATH%"
set "_BACKEND_PYTHONPATH="

if "%BACKEND_PID%"=="" (
  echo Failed to start lulu-agent backend. 1>&2
  exit /b 1
)

rem 等待后端可用
call :wait_for_url "http://%BACKEND_HOST%:%BACKEND_PORT%/health"
if errorlevel 1 (
  echo Backend did not become ready in time. 1>&2
  exit /b 1
)

rem 开启前端
echo Starting lulu-agent GUI: http://127.0.0.1:%FRONTEND_PORT%
call :start_process FRONTEND_PID "%NPM_EXE%" "run dev --prefix gui -- --port %FRONTEND_PORT% --strictPort" "%ROOT_DIR%" "VITE_API_BASE" "http://%BACKEND_HOST%:%BACKEND_PORT%" "VITE_WS_BASE" "ws://%BACKEND_HOST%:%BACKEND_PORT%"

if "%FRONTEND_PID%"=="" (
  echo Failed to start lulu-agent GUI. 1>&2
  exit /b 1
)

rem 等待前端可用
call :wait_for_url "http://127.0.0.1:%FRONTEND_PORT%"
if errorlevel 1 (
  echo GUI did not become ready in time. 1>&2
  exit /b 1
)

rem 启动 GUI
echo lulu-agent GUI is starting.
echo Open: http://127.0.0.1:%FRONTEND_PORT%
echo Press Ctrl+C to stop both processes.

start "" "http://127.0.0.1:%FRONTEND_PORT%"

rem 轮询检查前后端进程状态
:monitor
timeout /t 1 /nobreak >nul
tasklist /FI "PID eq %BACKEND_PID%" 2>nul | find "%BACKEND_PID%" >nul
if errorlevel 1 (
  echo Backend exited.
  exit /b 1
)
tasklist /FI "PID eq %FRONTEND_PID%" 2>nul | find "%FRONTEND_PID%" >nul
if errorlevel 1 (
  echo GUI exited.
  exit /b 1
)
goto :monitor

rem 清理进程
:cleanup
if not "%FRONTEND_PID%"=="" taskkill /PID %FRONTEND_PID% /T /F >nul 2>nul
if not "%BACKEND_PID%"=="" taskkill /PID %BACKEND_PID% /T /F >nul 2>nul
exit /b 0

rem 启动进程
:start_process
set "%~1="
set "_START_FILE=%~2"
set "_START_ARGS=%~3"
set "_START_CWD=%~4"
set "_START_ENV_NAME_1=%~5"
set "_START_ENV_VALUE_1=%~6"
set "_START_ENV_NAME_2=%~7"
set "_START_ENV_VALUE_2=%~8"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$envName1 = $env:_START_ENV_NAME_1; $envValue1 = $env:_START_ENV_VALUE_1; if ($envName1) { Set-Item -Path ('Env:' + $envName1) -Value $envValue1 }; $envName2 = $env:_START_ENV_NAME_2; $envValue2 = $env:_START_ENV_VALUE_2; if ($envName2) { Set-Item -Path ('Env:' + $envName2) -Value $envValue2 }; $p = Start-Process -FilePath $env:_START_FILE -ArgumentList $env:_START_ARGS -WorkingDirectory $env:_START_CWD -PassThru -NoNewWindow; $p.Id"`) do set "%~1=%%I"
set "_START_FILE="
set "_START_ARGS="
set "_START_CWD="
set "_START_ENV_NAME_1="
set "_START_ENV_VALUE_1="
set "_START_ENV_NAME_2="
set "_START_ENV_VALUE_2="
exit /b 0

rem 查找可用端口
:find_available_port
set "%~1="
set "_PORT_START=%~2"
set /a "_PORT_END=%~2+100"
for /l %%P in (%_PORT_START%,1,%_PORT_END%) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse('127.0.0.1'), %%P); $available = $false; try { $listener.Start(); $available = $true } catch {} finally { if ($listener) { $listener.Stop() } }; if ($available) { exit 0 } else { exit 1 }" >nul 2>nul
  if not errorlevel 1 (
    set "%~1=%%P"
    set "_PORT_START="
    set "_PORT_END="
    exit /b 0
  )
)
set "_PORT_START="
set "_PORT_END="
exit /b 1

rem 等待 URL 可用
:wait_for_url
set "_WAIT_URL=%~1"
for /l %%I in (1,1,40) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri $env:_WAIT_URL -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
  if not errorlevel 1 (
    set "_WAIT_URL="
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)
set "_WAIT_URL="
exit /b 1
