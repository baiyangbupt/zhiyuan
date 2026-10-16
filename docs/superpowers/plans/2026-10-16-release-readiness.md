# 发布就绪收口实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 在当前工作区逐项执行；禁止提交、创建分支、发布或重启现有服务。

**Goal:** 补齐内部调用脚本鉴权，修复前端类型和依赖锁，恢复可解释的离线质量门禁。

**Architecture:** 沿用上一批 `X-Internal-Service-Token` 契约，脚本共用标准库传输模块。SSH 的 curl 配置通过 stdin 传递，凭证不进入进程参数，内部请求禁止重定向。前端保持现有产品行为，修复真实类型根因而非降级严格检查；流式测试按生命周期验证，数据夹具单独预检。

**Tech Stack:** Python 3.10 / pytest、Node 22 / node:test、TypeScript 4.9 / Next 13、npm/yarn lockfile。

**Spec:** 用户已确认的本轮范围（上一条回复的第一、第二优先项）；鉴权契约见 `docs/superpowers/reviews/2026-10-16-internal-auth-rollout.md`。

## Global Constraints

- 保留全部现有工作区修改与其他工作线产物，不改实际密钥、不写共享数据库、不执行生产采集或回放。
- 不修改自动预填产品行为，不启用多 worker，不把深层架构改造混入本批。
- 凭证仅来自 `INTERNAL_SERVICE_TOKEN`；缺失或不合法时本地拒绝，不回显响应正文或 stderr 到异常。
- 仅离线或隔离验证；不得污染运行中的 Next 构建目录或原有 `tsconfig.tsbuildinfo`。

## Task 1: 迁移脚本传输

**Files:** 新增 `scripts/internal_http.py`、`zhiyuan-agent/tests/unit/test_script_internal_auth.py`；修改三个生产资产/验证/本地回放脚本。

- [x] 用替身传输复现缺少鉴权；覆盖缺省/CRLF 凭证、重定向、非 2xx、敏感错误、SSH 参数与 stdin、安全引号和公共取票不携带服务凭证。
- [x] 运行新用例，确认因旧传输契约不满足而失败（首次 45 failed / 2 passed）。
- [x] 实现共用传输，三个入口接入；运行用例及现有运维鉴权测试，并用真实宿主 curl 7.29 / urllib 回环夹具验证。

## Task 2: 修复前端门禁

**Files:** `subjectScores/index.tsx`、`userCenter/index.tsx`、`Header/index.tsx`、`service/index.ts`、`utils/tool.ts` 及用户信息类型定义；`package.json`、两份锁文件、`next.config.mjs`；新增相邻工具测试。请求头错误通过收紧 `getYuzhiToken` 返回类型从源头修复，不修改 Axios 调用点。

- [x] 运行 `tsc --noEmit --incremental false --pretty false` 重现 24 条类型错误，检查现有数据和组件契约。
- [x] 先补运行时回归测试，再修复类型根因；不使用 `any`/断言掩盖未知输入，不让展示组件伪装为可编辑组件。
- [x] 修复 `webpack-sources` 锁定版本与 webpack 的要求，核验 npm/yarn 一致性和本地缓存包 SHA512，虚拟依赖图无无效边。
- [x] 提供可执行的类型与单元测试命令，恢复 Next 类型检查；lint 沿用已有豁免，明确未恢复。

## Task 3: 恢复测试契约

**Files:** `zhiyuan-agent/tests/integration/test_gateway_live_events.py`、数据夹具校验用例及相关 runner/preflight。

- [x] 精确复现三条事件顺序断言，按 `turn.started`、业务事件、终态语义检查，保留内容和身份断言。
- [x] 区分纯单元样例结构检查与本地私有夹具预检；预检缺失退出 2，先于全部子命令，不伪造数据或静默跳过真实回放。
- [x] 完成定向及扩展离线验证，记录已通过项目和仍需授权的上线验收。

## Progress

- 本轮代码及定向、扩展离线验证完成；结果见 `docs/superpowers/reviews/2026-10-16-release-readiness-handoff.md`。
- 私有夹具仍缺 94 条引用，真实动作回放和部署必须另行授权，不作为本轮离线测试通过项。
