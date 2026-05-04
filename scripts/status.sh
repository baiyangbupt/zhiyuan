#!/bin/bash
#
# 查看所有服务运行状态
# 用法: bash scripts/status.sh
#

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "================================================"
echo "  智愿 AI 志愿填报系统 — 服务状态"
echo "================================================"
echo ""

check_service() {
    local name=$1
    local port=$2
    local pidfile=".pids/${name}.pid"
    local status="⬡ 停止"
    local pid="-"
    local health=""

    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            status="⬢ 运行中"
            # 检查端口是否可达
            if curl -sf "http://localhost:$port" > /dev/null 2>&1 || \
               curl -sf "http://localhost:$port/health" > /dev/null 2>&1 || \
               curl -sf "http://localhost:$port/docs" > /dev/null 2>&1; then
                health="(端口可达)"
            else
                health="(启动中...)"
            fi
        else
            status="⬡ 已退出"
            pid="$pid (dead)"
        fi
    fi

    printf "  %-14s %-10s PID: %-12s Port: %-6s %s\n" "$name" "$status" "$pid" "$port" "$health"
}

echo "▸ 应用服务"
check_service "web" "3001"
check_service "server" "8080"
check_service "agent" "8000"
check_service "rank" "5001"
echo ""

echo "▸ 基础设施"
printf "  %-14s " "MySQL"
if mysqladmin ping &>/dev/null 2>&1; then
    echo "⬢ 运行中   Port: 3306"
else
    echo "⬡ 停止"
fi

printf "  %-14s " "Redis"
if redis-cli ping &>/dev/null 2>&1; then
    echo "⬢ 运行中   Port: 6379"
else
    echo "⬡ 停止"
fi
echo ""

echo "▸ 日志文件"
for f in logs/*.log; do
    [ -f "$f" ] && printf "  %-28s %s\n" "$f" "$(wc -l < "$f") 行"
done 2>/dev/null || echo "  (无日志)"
echo ""
echo "================================================"
