#!/bin/bash
# 运行端到端测试脚本（需要真实 API key）

set -e

echo "=========================================="
echo "运行端到端测试（真实 LLM 调用）"
echo "=========================================="
echo ""

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "❌ .env 文件不存在"
    echo "请先创建 .env 文件并填入真实的 API key："
    echo "  cp .env.example .env"
    echo "  vim .env"
    exit 1
fi

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ 虚拟环境不存在，请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[test]'"
    exit 1
fi

# 显示当前配置
echo "📋 当前 LLM 配置："
grep "^LLM_" .env | grep -v "API_KEY" || true
echo ""

# 提示用户
echo "⚠️  警告：此测试会调用真实的 LLM API，可能产生费用"
echo ""
read -p "确认继续？(y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

echo ""
echo "🚀 运行端到端测试..."
pytest tests/e2e/ -v -s -m e2e --tb=short

echo ""
echo "=========================================="
echo "✅ 端到端测试完成"
echo "=========================================="
