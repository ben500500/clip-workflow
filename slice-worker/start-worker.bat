@echo off
REM =============================================================================
REM Clip Workflow 分布式切片节点启动脚本（Windows）
REM
REM 前置要求：
REM   1. Python 3.10+（引擎为纯标准库，无需 pip 装包；3.14 可用）
REM   2. ffmpeg 在 PATH 中（需含 libx264 + aac；要接字幕烧录任务还需 libass）
REM
REM 用法（可双击运行，或命令行带参数）：
REM   start-worker.bat --node-id win-node-1 --server-ip 192.168.1.163 --redis-password XXX
REM
REM 首次运行会在本目录生成 worker.json；再次运行同命令即按该配置重启节点。
REM 建议常驻：把本脚本的快捷方式放进 shell:startup（开机自启）。
REM =============================================================================
setlocal enabledelayedexpansion
set DIR=%~dp0
set NODE_ID=slice-worker-%COMPUTERNAME%
if defined NODE_ID_PREFIX set NODE_ID=%NODE_ID_PREFIX%%COMPUTERNAME%
set SERVER_IP=192.168.1.163
set REDIS_PASSWORD=
set MAX_CONCURRENT=1
set PRODUCT_CONCURRENCY=1
set CPU_PERCENT=50
set PYTHON_BIN=python3

:parse
if "%~1"=="" goto run
if /i "%~1"=="--node-id" ( set NODE_ID=%~2 & shift & shift & goto parse )
if /i "%~1"=="--server-ip" ( set SERVER_IP=%~2 & shift & shift & goto parse )
if /i "%~1"=="--redis-password" ( set REDIS_PASSWORD=%~2 & shift & shift & goto parse )
if /i "%~1"=="--max-concurrent" ( set MAX_CONCURRENT=%~2 & shift & shift & goto parse )
if /i "%~1"=="--product-concurrency" ( set PRODUCT_CONCURRENCY=%~2 & shift & shift & goto parse )
if /i "%~1"=="--cpu-percent" ( set CPU_PERCENT=%~2 & shift & shift & goto parse )
if /i "%~1"=="--python" ( set PYTHON_BIN=%~2 & shift & shift & goto parse )
echo 未知参数: %~1
exit /b 1

:run
%PYTHON_BIN% --version || (echo 需要 Python 3.10+ 且在 PATH 中 & pause & exit /b 1)

> "%DIR%worker.json" (
  echo {
  echo   "node_id": "%NODE_ID%",
  echo   "redis_url": "redis://:%REDIS_PASSWORD%@%SERVER_IP%:6379/0",
  echo   "tags": ["cpu"],
  echo   "max_concurrent": %MAX_CONCURRENT%,
  echo   "engines_path": "%DIR%engines",
  echo   "temp_dir": "%DIR%temp",
  echo   "log_level": "info",
  echo   "heartbeat_interval": 10,
  echo   "task_timeout": 21600,
  echo   "max_retries": 2,
  echo   "retry_delay": 30,
  echo   "backend_url": "http://%SERVER_IP%",
  echo   "cpu_percent": %CPU_PERCENT%,
  echo   "product_concurrency": %PRODUCT_CONCURRENCY%,
  echo   "stuck_task_minutes": 30,
  echo   "enable_direct_queue": true,
  echo   "direct_queue_timeout": 2
  echo }
)
if not exist "%DIR%temp" mkdir "%DIR%temp"
set SLICE_PYTHON=%PYTHON_BIN%
echo 启动节点 %NODE_ID%（本窗口保持开启；关闭窗口即停止节点）
cd /d "%DIR%"
slice-worker.exe --config "%DIR%worker.json" --no-tui
pause
