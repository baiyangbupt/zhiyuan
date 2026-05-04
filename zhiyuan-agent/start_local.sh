#!/bin/bash

# 启动 WebSocket 服务器脚本

echo "🚀 启动高考志愿填报 WebSocket 服务..."
echo ""

# 激活虚拟环境
source .venv/bin/activate

# 启动服务器
uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload

echo ""
echo "✅ 服务器已启动在 http://localhost:8000"
echo "📡 WebSocket 端点: ws://localhost:8000/ws/chat"
