#!/bin/bash
# 运行单元测试脚本

set -e

echo "=========================================="
echo "运行单元测试（不需要 API key）"
echo "=========================================="
echo ""

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ 虚拟环境不存在，请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[test]'"
    exit 1
fi

# 运行单元测试和集成测试（不包括 e2e）
echo "📦 运行单元测试..."
pytest tests/unit/ tests/integration/ -v --tb=short

echo ""
echo "=========================================="
echo "✅ 单元测试完成"
echo "=========================================="
