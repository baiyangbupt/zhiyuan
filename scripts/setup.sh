#!/bin/bash
#
# 一键初始化本地开发环境
# 用法: bash scripts/setup.sh
#

set -e
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "================================================"
echo "  智愿 AI 志愿填报系统 — 本地环境初始化"
echo "================================================"
echo ""

# ─── 检查基础依赖 ───────���───────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "❌ 未找到 $1，请先安装"
        echo "   $2"
        return 1
    fi
    echo "✓ $1 $(command -v $1)"
}

echo "▸ 检查依赖..."
check_cmd node "brew install node (需要 >= 22)"
check_cmd npm ""
check_cmd java "brew install openjdk@8"
check_cmd mvn "brew install maven"
check_cmd python3 "brew install python@3.12"
check_cmd mysql "brew install mysql"
check_cmd redis-cli "brew install redis"
echo ""

# ─── 前端 (zhiyuan-web) ────────────────────────────
echo "▸ [zhiyuan-web] 安装 npm 依赖..."
cd "$ROOT_DIR/zhiyuan-web"
npm install --silent
echo "  ✓ 依赖安装完成"
echo ""

# ─── 后端 (zhiyuan-server) ─────────────────────────
echo "▸ [zhiyuan-server] Maven 编译..."
cd "$ROOT_DIR/zhiyuan-server"
mvn compile -q -DskipTests
echo "  ✓ 编译完成"
echo ""

# ─── Agent (zhiyuan-agent) ─────────────────────────
echo "▸ [zhiyuan-agent] 创建虚拟环境并安装..."
cd "$ROOT_DIR/zhiyuan-agent"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -e . --quiet
deactivate
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ⚠ 已创建 .env 文件，请填入 LLM_API_KEY"
fi
echo "  ✓ 安装完成"
echo ""

# ─── Rank (zhiyuan-rank) ──────────────────────────
echo "▸ [zhiyuan-rank] 创建虚拟环境并安装..."
cd "$ROOT_DIR/zhiyuan-rank"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt --quiet
deactivate
echo "  ✓ 安装完成"
echo ""

# ─── MySQL 初始化 ─────────────────────────────────
echo "▸ 检查 MySQL..."
if mysql -uroot -e "SELECT 1" &>/dev/null 2>&1; then
    echo "  ✓ MySQL 可连接"
    if ! mysql -uroot -e "USE gaotu_zhiyuan" &>/dev/null 2>&1; then
        echo "  ▸ 创建数据库 gaotu_zhiyuan..."
        mysql -uroot -e "CREATE DATABASE IF NOT EXISTS gaotu_zhiyuan DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        if [ -f "$ROOT_DIR/zhiyuan-server/script/db/ddl.sql" ]; then
            mysql -uroot gaotu_zhiyuan < "$ROOT_DIR/zhiyuan-server/script/db/ddl.sql"
            echo "  ✓ 表结构已导入"
        fi
    else
        echo "  ✓ 数据库 gaotu_zhiyuan 已存在"
    fi
else
    echo "  ⚠ MySQL 未运行或需要密码，请手动初始化："
    echo "    mysql -uroot -e 'CREATE DATABASE gaotu_zhiyuan ...'"
fi
echo ""

# ─── Redis 检查 ───────────────────────────────────
echo "▸ 检查 Redis..."
if redis-cli ping &>/dev/null; then
    echo "  ✓ Redis 已运行"
else
    echo "  ⚠ Redis 未运行，请执行: brew services start redis"
fi
echo ""

echo "================================================"
echo "  ✅ 初始化完成！"
echo ""
echo "  启动所有服务: bash scripts/start-all.sh"
echo "  查看服务状态: bash scripts/status.sh"
echo "================================================"
