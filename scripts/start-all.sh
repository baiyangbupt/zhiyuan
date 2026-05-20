#!/bin/bash
#
# 启动所有本地服务
# 用法: bash scripts/start-all.sh [--skip-infra]
#
# 服务进程 PID 记录在 .pids/ 目录，供 stop-all.sh 使用
#

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p .pids logs

SKIP_INFRA=false
for arg in "$@"; do
    [ "$arg" = "--skip-infra" ] && SKIP_INFRA=true
done

echo "================================================"
echo "   AI 志愿填报系统 — 启动服务"
echo "================================================"
echo ""

# ─── 基础设施 ─────────────────────────────────────
if [ "$SKIP_INFRA" = false ]; then
    echo "▸ 检查 MySQL..."
    if ! mysqladmin ping &>/dev/null 2>&1; then
        echo "  启�� MySQL..."
        brew services start mysql 2>/dev/null || echo "  ⚠ 请手动启动 MySQL"
        sleep 2
    fi
    echo "  ✓ MySQL 就绪"

    echo "▸ 检查 Redis..."
    if ! redis-cli ping &>/dev/null 2>&1; then
        echo "  启动 Redis..."
        brew services start redis 2>/dev/null || echo "  ⚠ 请手动启动 Redis"
        sleep 1
    fi
    echo "  ✓ Redis 就绪"
    echo ""
fi

# ─── zhiyuan-rank (端口 5001) ────────────────────
echo "▸ [zhiyuan-rank] 启动排序服务..."
if [ -f .pids/rank.pid ] && kill -0 "$(cat .pids/rank.pid)" 2>/dev/null; then
    echo "  ⏭ 已在运行 (PID $(cat .pids/rank.pid))"
else
    cd "$ROOT_DIR/zhiyuan-rank"
    source .venv/bin/activate
    nohup python app.py > "$ROOT_DIR/logs/rank.log" 2>&1 &
    echo $! > "$ROOT_DIR/.pids/rank.pid"
    deactivate
    echo "  ✓ 已启动 (PID $(cat $ROOT_DIR/.pids/rank.pid)) → http://localhost:5001"
fi
echo ""

# ─── zhiyuan-server (端口 8080) ──────────────────
echo "▸ [zhiyuan-server] 启动业务后端..."
if [ -f .pids/server.pid ] && kill -0 "$(cat .pids/server.pid)" 2>/dev/null; then
    echo "  ⏭ 已在运行 (PID $(cat .pids/server.pid))"
else
    cd "$ROOT_DIR/zhiyuan-server"
    nohup mvn spring-boot:run -Dspring-boot.run.profiles=local -q > "$ROOT_DIR/logs/server.log" 2>&1 &
    echo $! > "$ROOT_DIR/.pids/server.pid"
    echo "  ✓ 已启动 (PID $(cat $ROOT_DIR/.pids/server.pid)) → http://localhost:8080"
    echo "  ⏳ Spring Boot 启动需要 10-20 秒..."
fi
echo ""

# ─── zhiyuan-agent (端口 8000) ───────────────────
echo "▸ [zhiyuan-agent] 启动 AI Agent..."
if [ -f .pids/agent.pid ] && kill -0 "$(cat .pids/agent.pid)" 2>/dev/null; then
    echo "  ⏭ 已在运行 (PID $(cat .pids/agent.pid))"
else
    cd "$ROOT_DIR/zhiyuan-agent"
    source .venv/bin/activate
    nohup uvicorn app.server:app --host 127.0.0.1 --port 8000 > "$ROOT_DIR/logs/agent.log" 2>&1 &
    echo $! > "$ROOT_DIR/.pids/agent.pid"
    deactivate
    echo "  ✓ 已启动 (PID $(cat $ROOT_DIR/.pids/agent.pid)) → http://localhost:8000"
fi
echo ""

# ─── zhiyuan-web (端口 3001) ─────────────────────
echo "▸ [zhiyuan-web] 启动前端开发服务器..."
if [ -f .pids/web.pid ] && kill -0 "$(cat .pids/web.pid)" 2>/dev/null; then
    echo "  ⏭ 已在运行 (PID $(cat .pids/web.pid))"
else
    cd "$ROOT_DIR/zhiyuan-web"
    nohup ./node_modules/.bin/env-cmd -f .env.dev ./node_modules/.bin/next dev -H 127.0.0.1 -p 3001 > "$ROOT_DIR/logs/web.log" 2>&1 &
    echo $! > "$ROOT_DIR/.pids/web.pid"
    echo "  ✓ 已启动 (PID $(cat $ROOT_DIR/.pids/web.pid)) → http://localhost:3001"
fi
echo ""

echo "================================================"
echo "  ✅ 所有服务已启动"
echo ""
echo "  前端:   http://localhost:3001"
echo "  后端:   http://localhost:8080"
echo "  Agent:  http://localhost:8000"
echo "  Rank:   http://localhost:5001"
echo ""
echo "  查看日志: tail -f logs/<service>.log"
echo "  停止服务: bash scripts/stop-all.sh"
echo "  查看状态: bash scripts/status.sh"
echo "================================================"
