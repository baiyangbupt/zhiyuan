#!/bin/bash
#
# 停止所有本地服务
# 用法: bash scripts/stop-all.sh [--include-infra]
#

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

INCLUDE_INFRA=false
for arg in "$@"; do
    [ "$arg" = "--include-infra" ] && INCLUDE_INFRA=true
done

echo "================================================"
echo "  智愿 AI 志愿填报系统 — 停止服务"
echo "================================================"
echo ""

stop_service() {
    local name=$1
    bash "$ROOT_DIR/scripts/stop.sh" "$name"
}

echo "▸ 停止应用服务..."
stop_service "web"
stop_service "agent"
stop_service "server"
stop_service "rank"
echo ""

# 清理可能残留的 Java 进程 (spring-boot:run 会 fork 子进程)
JAVA_PID=$(pgrep -f "zhiyuan-server" 2>/dev/null)
if [ -n "$JAVA_PID" ]; then
    kill "$JAVA_PID" 2>/dev/null
    echo "  ✓ 清理残留 Java 进程 (PID $JAVA_PID)"
fi

if [ "$INCLUDE_INFRA" = true ]; then
    echo "▸ 停止基础设施..."
    brew services stop mysql 2>/dev/null && echo "  ✓ MySQL 已停止" || true
    brew services stop redis 2>/dev/null && echo "  ✓ Redis 已停止" || true
    echo ""
fi

echo "================================================"
echo "  ✅ 所有服务已停止"
echo "================================================"
