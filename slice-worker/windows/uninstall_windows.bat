@echo off
chcp 65001 >nul
REM =============================================================================
REM  Clip Workflow - Windows 端 Slice Worker 卸载脚本
REM  功能：停止正在运行的 Worker -> 取消开机自启 -> （可选）删除配置/二进制
REM  用法：uninstall_windows.bat [--purge]
REM        不带参数：仅停止进程 + 取消开机自启（保留程序文件）
REM        --purge   ：同时删除 slice-worker.exe / worker.json / temp 目录
REM =============================================================================
setlocal

set "PURGE="
if /i "%~1"=="--purge" set "PURGE=1"
if /i "%~1"=="-p"      set "PURGE=1"

set "SCRIPT_DIR=%~dp0"

REM ==================== 停止进程 ====================
echo [INFO] 停止正在运行的 Slice Worker ...
taskkill /IM slice-worker.exe /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] 未发现运行中的 slice-worker.exe
) else (
    echo [INFO] 已停止 slice-worker.exe
)

REM ==================== 取消开机自启 ====================
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ClipSliceWorker" /f >nul 2>&1
if errorlevel 1 (
    echo [INFO] 开机自启项不存在或已删除
) else (
    echo [INFO] 已取消开机自启
)

REM ==================== 可选清理 ====================
if defined PURGE (
    echo [INFO] 清理部署文件...
    if exist "%SCRIPT_DIR%slice-worker.exe" del /q "%SCRIPT_DIR%slice-worker.exe" >nul 2>&1 && echo   - 已删除 slice-worker.exe
    if exist "%SCRIPT_DIR%worker.json"     del /q "%SCRIPT_DIR%worker.json"     >nul 2>&1 && echo   - 已删除 worker.json
    if exist "%SCRIPT_DIR%temp"            rmdir /s /q "%SCRIPT_DIR%temp"       >nul 2>&1 && echo   - 已删除 temp 目录
    if exist "%SCRIPT_DIR%slice-worker.log" del /q "%SCRIPT_DIR%slice-worker.log" >nul 2>&1
    echo [INFO] 清理完成
) else (
    echo [INFO] 已停止 Worker 并取消开机自启（程序文件已保留）
    echo        如需彻底删除文件, 请运行: %~nx0 --purge
)

echo.
echo [INFO] 卸载完成
pause
