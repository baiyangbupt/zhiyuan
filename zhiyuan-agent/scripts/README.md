# 测试脚本说明

## 可用脚本

### 1. `run_unit_tests.sh` — 运行单元测试
```bash
./scripts/run_unit_tests.sh
```
- ✅ 不需要 API key
- ✅ 运行速度快（< 1 秒）
- 测试范围：`tests/unit/` + `tests/integration/`
- 共 33 个测试用例

### 2. `run_e2e_tests.sh` — 运行端到端测试
```bash
./scripts/run_e2e_tests.sh
```
- ⚠️ 需要真实 API key（.env 文件）
- ⚠️ 会产生 API 调用费用
- 测试范围：`tests/e2e/`
- 共 5 个测试用例
- 运行前会提示确认

### 3. `run_all_tests.sh` — 运行所有测试
```bash
./scripts/run_all_tests.sh
```
- 先运行单元测试
- 再运行端到端测试（可选）
- 如果没有 .env 文件，自动跳过端到端测试

### 4. `run_tests_with_coverage.sh` — 测试 + 覆盖率报告
```bash
./scripts/run_tests_with_coverage.sh
```
- 运行单元测试
- 生成代码覆盖率报告
- 输出：终端 + HTML 报告（`htmlcov/index.html`）

## 快速开始

```bash
# 1. 首次使用：创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'

# 2. 运行单元测试（无需配置）
./scripts/run_unit_tests.sh

# 3. 配置 .env 文件（如需端到端测试）
cp .env.example .env
vim .env  # 填入真实 API key

# 4. 运行端到端测试
./scripts/run_e2e_tests.sh

# 5. 运行所有测试
./scripts/run_all_tests.sh
```

## 注意事项

- 所有脚本会自动激活虚拟环境（`.venv`）
- 端到端测试运行前会显示当前配置并要求确认
- 如果虚拟环境不存在，脚本会提示创建命令
