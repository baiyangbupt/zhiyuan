#!/bin/bash
# 运行测试并生成覆盖率报告

set -e

echo "=========================================="
echo "运行测试 + 生成覆盖率报告"
echo "=========================================="
echo ""

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ 虚拟环境不存在，请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[test]'"
    exit 1
fi

# 检查是否安装了 pytest-cov
if ! pip show pytest-cov > /dev/null 2>&1; then
    echo "📦 安装 pytest-cov..."
    pip install pytest-cov -q
fi

# 运行单元测试 + 覆盖率
echo "🔍 运行测试并生成覆盖率报告..."
pytest tests/unit/ tests/integration/ \
    --cov=app \
    --cov-report=term-missing \
    --cov-report=html \
    -v

echo ""
echo "=========================================="
echo "✅ 测试完成"
echo "=========================================="
echo ""
echo "📊 覆盖率报告已生成："
echo "  - 终端输出：见上方"
echo "  - HTML 报告：htmlcov/index.html"
echo ""
echo "查看 HTML 报告："
echo "  open htmlcov/index.html"
