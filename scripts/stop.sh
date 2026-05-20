#!/bin/bash
#
# 停止单个服务
# 用法: bash scripts/stop.sh <web|server|agent|rank>
#

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/service-common.sh"

SERVICE=$1

if [ -z "$SERVICE" ]; then
    echo "用法: bash scripts/stop.sh <web|server|agent|rank>"
    exit 1
fi

pidfile=$(service_pidfile "$SERVICE")
port_pids=$(service_listen_pids "$SERVICE")
pid=""

if [ ! -f "$pidfile" ]; then
    :
else
    pid=$(cat "$pidfile")
fi

if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    wait=0
    while kill -0 "$pid" 2>/dev/null && [ $wait -lt 3 ]; do
        sleep 1
        wait=$((wait + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null
    fi
    echo "✓ ${SERVICE} 已停止 (PID $pid)"
else
    if [ -n "$pid" ]; then
        echo "⏭ ${SERVICE} 已退出 (PID $pid)"
    else
        echo "⏭ ${SERVICE} 未在运行 (无 PID 文件)"
    fi
fi
rm -f "$pidfile"

# 如果 PID 文件失效但端口还在监听，清理端口监听进程
for port_pid in $port_pids; do
    if [ -n "$pid" ] && [ "$port_pid" = "$pid" ]; then
        continue
    fi
    if kill -0 "$port_pid" 2>/dev/null; then
        kill "$port_pid" 2>/dev/null
        wait=0
        while kill -0 "$port_pid" 2>/dev/null && [ $wait -lt 3 ]; do
            sleep 1
            wait=$((wait + 1))
        done
        if kill -0 "$port_pid" 2>/dev/null; then
            kill -9 "$port_pid" 2>/dev/null
        fi
        echo "  清理端口监听进程 (PID $port_pid, Port $(service_port "$SERVICE"))"
    fi
done

# 后端 spring-boot:run 会 fork 子进程，需要额外清理
if [ "$SERVICE" = "server" ]; then
    JAVA_PID=$(pgrep -f "zhiyuan-server" 2>/dev/null)
    if [ -n "$JAVA_PID" ]; then
        kill "$JAVA_PID" 2>/dev/null
        echo "  清理 Java 子进程 (PID $JAVA_PID)"
    fi
fi
