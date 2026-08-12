#!/bin/bash
# launchd 启动 wrapper：cd 到正确目录后启动 slice worker（托盘模式）
cd "$(dirname "$0")"
exec ./slice-worker-mac --config worker.json --tray
