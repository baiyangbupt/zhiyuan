#!/bin/bash
# 运行所有测试（单元测试 + 端到端测试）

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "=========================================="
echo "运行所有测试"
echo "=========================================="
echo ""

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "⚠️  .env 文件不存在，将跳过端到端测试"
    echo ""
    echo "如需运行端到端测试，请创建 .env 文件："
    echo "  cp .env.example .env"
    echo "  vim .env"
    echo ""
    SKIP_E2E=true
else
    SKIP_E2E=false
fi

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ 虚拟环境不存在，请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[test]'"
    exit 1
fi

# 运行单元测试
echo "📦 1/2 运行单元测试..."
python -m pytest tests/unit/ tests/integration/ -v --tb=short
echo ""

# 运行端到端测试
if [ "$SKIP_E2E" = false ]; then
    echo "📋 当前 LLM 配置："
    grep "^LLM_" .env | grep -v "API_KEY" || true
    echo ""
    echo "⚠️  警告：端到端测试会调用真实的 LLM API，可能产生费用"
    echo ""
    read -p "是否运行端到端测试？(y/N) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "🚀 2/2 运行端到端测试..."
        python -m pytest tests/e2e/ -v -s -m e2e --tb=short
    else
        echo "⏭️  跳过端到端测试"
    fi
else
    echo "⏭️  跳过端到端测试（.env 文件不存在）"
fi

echo ""
echo "=========================================="
echo "✅ 测试完成"
echo "=========================================="
