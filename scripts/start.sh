#!/bin/bash
#
# 启动单个服务
# 用法: bash scripts/start.sh <web|server|agent|rank>
#

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p .pids logs

SERVICE=$1

if [ -z "$SERVICE" ]; then
    echo "用法: bash scripts/start.sh <web|server|agent|rank>"
    echo ""
    echo "  web     前端开发服务器 (端口 3001)"
    echo "  server  业务后端 (端口 8080)"
    echo "  agent   AI Agent (端口 8000)"
    echo "  rank    排序服务 (端口 5001)"
    exit 1
fi

if [ -f ".pids/${SERVICE}.pid" ] && kill -0 "$(cat .pids/${SERVICE}.pid)" 2>/dev/null; then
    echo "⏭ ${SERVICE} 已在运行 (PID $(cat .pids/${SERVICE}.pid))"
    exit 0
fi

case $SERVICE in
    web)
        cd "$ROOT_DIR/zhiyuan-web"
        nohup npx env-cmd -f .env.dev next dev -p 3001 > "$ROOT_DIR/logs/web.log" 2>&1 &
        echo $! > "$ROOT_DIR/.pids/web.pid"
        echo "✓ zhiyuan-web 已启动 → http://localhost:3001"
        ;;
    server)
        cd "$ROOT_DIR/zhiyuan-server"
        nohup mvn spring-boot:run -Dspring-boot.run.profiles=local -q > "$ROOT_DIR/logs/server.log" 2>&1 &
        echo $! > "$ROOT_DIR/.pids/server.pid"
        echo "✓ zhiyuan-server 已启动 → http://localhost:8080"
        echo "  ⏳ Spring Boot 需要 10-20 秒完成启动"
        ;;
    agent)
        cd "$ROOT_DIR/zhiyuan-agent"
        source .venv/bin/activate
        nohup uvicorn app.server:app --host 0.0.0.0 --port 8000 > "$ROOT_DIR/logs/agent.log" 2>&1 &
        echo $! > "$ROOT_DIR/.pids/agent.pid"
        deactivate
        echo "✓ zhiyuan-agent 已启动 → http://localhost:8000"
        ;;
    rank)
        cd "$ROOT_DIR/zhiyuan-rank"
        source .venv/bin/activate
        nohup python app.py > "$ROOT_DIR/logs/rank.log" 2>&1 &
        echo $! > "$ROOT_DIR/.pids/rank.pid"
        deactivate
        echo "✓ zhiyuan-rank 已启动 → http://localhost:5001"
        ;;
    *)
        echo "❌ 未知服务: $SERVICE"
        echo "可选: web | server | agent | rank"
        exit 1
        ;;
esac
