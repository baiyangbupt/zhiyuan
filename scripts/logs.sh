#!/bin/bash
#
# 查看服务日志
# 用法: bash scripts/logs.sh <web|server|agent|rank> [--follow]
#

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SERVICE=$1
FOLLOW=${2:-}

if [ -z "$SERVICE" ]; then
    echo "用法: bash scripts/logs.sh <web|server|agent|rank> [--follow]"
    exit 1
fi

LOGFILE="$ROOT_DIR/logs/${SERVICE}.log"

if [ ! -f "$LOGFILE" ]; then
    echo "❌ 日志文件不存在: $LOGFILE"
    exit 1
fi

if [ "$FOLLOW" = "--follow" ] || [ "$FOLLOW" = "-f" ]; then
    tail -f "$LOGFILE"
else
    tail -100 "$LOGFILE"
fi
