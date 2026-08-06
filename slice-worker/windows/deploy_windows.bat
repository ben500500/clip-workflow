@echo off
chcp 65001 >nul
REM =============================================================================
REM  Clip Workflow - Windows 端 Slice Worker 一键部署脚本
REM  功能：检测环境 -> 下载/构建 Worker -> 生成配置 -> 注册为开机自启（任务栏托盘）
REM
REM  用法：
REM    deploy_windows.bat                      交互式部署（输入服务器 IP / Redis 密码）
REM    deploy_windows.bat --server-ip 1.2.3.4 --redis-password xxxx [--node-id NAME]
REM
REM  依赖（自动检测）：python3.10+（切片引擎）、ffmpeg（切片）、Go（仅离线构建时需要）
REM  说明：节点本地无需安装 Redis，只需网络可达服务器 Redis(6379)/后端(80) 端口。
REM =============================================================================
setlocal enabledelayedexpansion

set "SERVER_IP="
set "REDIS_PASSWORD="
set "NODE_ID="
set "REDIS_PORT=6379"
set "MAX_CONCURRENT=2"
set "CPU_PERCENT=50"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--server-ip"      ( set "SERVER_IP=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--redis-password" ( set "REDIS_PASSWORD=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--node-id"        ( set "NODE_ID=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--redis-port"     ( set "REDIS_PORT=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--max-concurrent" ( set "MAX_CONCURRENT=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--cpu-percent"     ( set "CPU_PERCENT=%~2" & shift & shift & goto parse_args )
if /i "%~1"=="--help"           goto usage
echo [ERROR] 未知参数: %~1
goto usage
:args_done

REM ==================== 帮助 ====================
:usage
echo.
echo 用法: deploy_windows.bat [--server-ip IP] [--redis-password PASS] [--node-id NAME]
echo       [--redis-port PORT] [--max-concurrent N] [--cpu-percent N]
echo.
echo 交互模式直接运行: deploy_windows.bat
echo 部署后 Worker 会以"任务栏托盘"方式运行（图标在右下角系统托盘），
echo 可从托盘菜单查看状态 / 启停节点 / 退出。
exit /b 1

REM ==================== 交互输入 ====================
if "%SERVER_IP%"=="" (
    set /p "SERVER_IP=请输入服务器 IP/域名: "
)
if "%SERVER_IP%"=="" (
    echo [ERROR] 未提供服务器 IP
    goto usage
)
if "%REDIS_PASSWORD%"=="" (
    set /p "REDIS_PASSWORD=请输入 Redis 密码（与服务器 .env 的 REDIS_PASSWORD 一致）: "
)
if "%REDIS_PASSWORD%"=="" (
    echo [ERROR] 未提供 Redis 密码
    goto usage
)
if "%NODE_ID%"=="" (
    for /f "tokens=*" %%i in ('hostname') do set "HOST_NAME=%%i"
    set "HOST_CLEAN=!HOST_NAME!"
    REM 简单截取前 12 个字符作为节点后缀
    if defined HOST_CLEAN set "NODE_ID=slice-worker-!HOST_CLEAN:~0,12!"
    if not defined NODE_ID set "NODE_ID=slice-worker-local"
)

REM ==================== 前置检查 ====================
echo.
echo [INFO] === 前置检查 ===
set "MISSING="
python --version >nul 2>&1
if errorlevel 1 set "MISSING=%MISSING% python"
ffmpeg -version >nul 2>&1
if errorlevel 1 set "MISSING=%MISSING% ffmpeg"

REM 网络连通性检查（Redis 端口）
powershell -NoProfile -Command "Test-NetConnection -ComputerName %SERVER_IP% -Port %REDIS_PORT% -InformationLevel Quiet" > "%TEMP%\cnb-nc.txt" 2>&1
set /p "REDIS_REACHABLE=" < "%TEMP%\cnb-nc.txt"
if /i not "%REDIS_REACHABLE%"=="True" (
    echo [WARN] 无法连通 %SERVER_IP%:%REDIS_PORT% ^(Redis^), 请检查网络/防火墙
)
del "%TEMP%\cnb-nc.txt" >nul 2>&1

if not "%MISSING%"=="" (
    echo [ERROR] 缺少必需工具: %MISSING%
    echo 请先安装:
    echo   - Python 3.10+    https://www.python.org/downloads/
    echo   - FFmpeg          https://www.gyan.dev/ffmpeg/builds/ ^(解压后把 bin 加入 PATH^)
    pause
    exit /b 1
)
echo [INFO] 前置检查通过: python + ffmpeg 已安装

REM ==================== 确定 Worker 二进制 ====================
echo.
echo [INFO] === 准备 Worker 程序 ===
set "SCRIPT_DIR=%~dp0"
set "WORKER_BIN=%SCRIPT_DIR%slice-worker.exe"
set "BUILD_NOW="
if not exist "%WORKER_BIN%" (
    echo [INFO] 未找到 slice-worker.exe, 尝试本地构建 ^(需要 Go^)...
    go version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] 未找到 Go 工具链, 且未提供预编译 slice-worker.exe
        echo 请先在本机安装 Go ^(https://go.dev/dl/^), 再运行本脚本;
        echo 或把构建好的 slice-worker.exe 放到本脚本同目录。
        pause
        exit /b 1
    )
    set "BUILD_NOW=1"
) else (
    echo [INFO] 使用已有二进制: %WORKER_BIN%
)

if defined BUILD_NOW (
    echo [INFO] 正在编译 Windows Worker ^(可能需要几分钟, 首次会下载依赖^)...
    pushd "%SCRIPT_DIR%.."
    set "GOPROXY=https://goproxy.cn,direct"
    go build -ldflags="-s -w" -o "%WORKER_BIN%" ./slice-worker
    if errorlevel 1 (
        echo [ERROR] 编译失败, 请检查 Go 环境/网络
        popd
        pause
        exit /b 1
    )
    popd
    echo [INFO] 编译完成
)

REM ==================== 生成配置 ====================
echo.
echo [INFO] === 生成 worker.json 配置 ===
REM 使用相对路径的 engines/temp, 便于移动目录
(
echo {
echo   "node_id": "%NODE_ID%",
echo   "redis_url": "redis://:%REDIS_PASSWORD%@%SERVER_IP%:%REDIS_PORT%/0",
echo   "tags": ["cpu"],
echo   "max_concurrent": %MAX_CONCURRENT%,
echo   "engines_path": "%SCRIPT_DIR%engines",
echo   "temp_dir": "%SCRIPT_DIR%temp",
echo   "log_level": "info",
echo   "heartbeat_interval": 10,
echo   "task_timeout": 7200,
echo   "max_retries": 2,
echo   "retry_delay": 30,
echo   "node_ttl": 0,
echo   "backend_url": "http://%SERVER_IP%",
echo   "cpu_percent": %CPU_PERCENT%
echo }
) > "%SCRIPT_DIR%worker.json"
echo [INFO] 配置已生成: %SCRIPT_DIR%worker.json

REM ==================== 启动（任务栏托盘） ====================
echo.
echo [INFO] === 启动 Worker（任务栏托盘模式）===
echo  节点ID:   %NODE_ID%
echo  服务器:   %SERVER_IP%:%REDIS_PORT%
echo  并发数:   %MAX_CONCURRENT%
echo  CPU分配:  %CPU_PERCENT%%
echo.
echo  启动后请留意系统托盘（右下角）出现 "Slice Worker" 图标:
echo    - 左键/右键点开可查看节点状态、启用/停用节点、退出
echo    - 首次启动会自动注册开机自启（当前用户）
echo.

start "Slice Worker" "%WORKER_BIN%" --config "%SCRIPT_DIR%worker.json" --tray

REM 注册开机自启（当前用户 HKCU）
set "STARTUP_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
reg add "%STARTUP_KEY%" /v "ClipSliceWorker" /t REG_SZ /d "\"%WORKER_BIN%\" --config \"%SCRIPT_DIR%worker.json\" --tray" /f >nul 2>&1
echo [INFO] 已注册开机自启（如需取消: 运行 uninstall_windows.bat 或删除注册表 ClipSliceWorker）

echo.
echo [INFO] 部署完成! 验证方式:
echo   1. 服务器端: 前端「Worker 节点」页面能看到本节点在线
echo   2. 后端日志: docker exec clip-redis redis-cli -a ^<密码^> --no-auth-warning smembers slice:nodes:online
echo   3. 尝试跑一条切片任务, 观察托盘图标/日志是否在处理
echo.
pause
