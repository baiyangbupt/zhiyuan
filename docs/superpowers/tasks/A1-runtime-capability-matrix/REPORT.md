---
task: A1
status: DONE_WITH_CONCERNS
executor: zhiyuan-07 (deepseek)
finished_at: 2026-09-20 22:05 +0800
source: docs/superpowers/plans/2026-09-20-codex-native-interaction.md
---

# A1 报告：固定运行时与原生能力兼容矩阵

## 一、结论

**原生问答这条路在真实二进制上通了。** 这是 A1 唯一要回答的问题，答案是"可用"，
但它附带了两个必须一起带走的条件（见第三节）。

| gate | 状态 | 证据强度 |
|---|---|---|
| `initialize`（声明 capabilities） | passed | 真实二进制 + 真实模型 |
| `threadStart`（`threadSource:"user"`） | passed | 真实二进制 |
| `resume`（换连接恢复） | passed | 真实二进制 |
| `requestUserInput`（原生提问 + 同 id 回包） | **passed** | 真实二进制 + 真实模型 |
| `trustedMcpMetadata`（MCP `_meta` 线程身份） | passed | 真实二进制 |
| `toolAllowlist`（有效 MCP 工具清单） | passed | 真实二进制 |
| `featurePolicy`（shell/exec 等必须关着） | **failed** | 真实二进制 |
| `elicitation`（MCP form） | **not_run** | 见第五节，两个形态都没测到 |

探针报告：`.runtime/codex-capabilities.json`（退出码 0 = 选中的 gates 全过）。

运行组合（必须与结论一起引用，换一个 provider 结论不成立）：

```
二进制：codex-cli 0.155.1（/root/.nvm/versions/node/v20.20.2/bin/codex）
源码：  /root/dev/codex @ 5c5308f（配置声明值，非二进制自证）
模型：  deepseek-flash，provider deepseek，base_url https://api.deepseek.com
开关：  features.default_mode_request_user_input=true
        tools.experimental_request_user_input.enabled=true
```

## 二、两个条件（缺一，上面的 passed 就不成立）

1. **必须带那两个特性开关。** 探针是在显式传 `-c features.default_mode_request_user_input=true`
   与 `-c tools.experimental_request_user_input.enabled=true` 的条件下拿到 passed 的。
   配置默认值因此写成保守的 `user_input_mode=structured_final`：开关没接上之前声明成
   native，就是把"没测过的组合"当默认。A4 用它决定走原生还是走结构化终态澄清。

2. **`deepseek-flash` 不在 codex 的模型元数据目录里。** 每次启动都会打印
   `Model metadata for 'deepseek-flash' not found. Defaulting to fallback metadata;
   this can degrade performance and cause issues.` 这不影响握手与提问，但意味着
   上下文窗口、工具调用风格等是按 fallback 猜的。换模型前需要重新探针。

## 二之二、工具面：`featurePolicy` 失败，且不是配置写错

设计 §7 要求"默认禁用 shell、任意 HTTP、代码执行、文件写入"，并明说
"仅设置 read-only sandbox/approvalPolicy 不足以证明工具不可调用"。实测：

```
默认启动（只带 approvalPolicy=never + sandbox=read-only）：
  shell_tool=True  unified_exec=True  unified_exec_tty=True  shell_snapshot=True
  browser_use=True computer_use=True  in_app_local_automation=True
  hooks=True       plugins=True       apps=True               image_generation=True
  default_mode_request_user_input=False   ← 原生提问默认是关的
```

- `--disable shell_tool`、`--disable browser_use`、`--disable computer_use`、
  `--disable in_app_local_automation` 都**生效**。
- `--disable unified_exec` **不生效**，它始终为 `True`。而 `unified_exec`
  同样是被模型调用的命令执行能力。所以"显式关闭 shell/exec"用现成开关
  **做不到**，`featurePolicy` 因此判 failed。
- 顺带确认了第二节条件 1 的成因：`default_mode_request_user_input` 是
  `underDevelopment` 且默认关闭，必须显式打开。

未继续往下做的原因：这已经越出"核对清单"，进入"改生产启动参数"的决策区。
可选方向有三条（都能查到但都没实施）：换用别的关闭机制；接受 read-only
sandbox 作为边界并把它写成明确的安全声明；或改用不含这些能力的运行组合。
**需要设计侧/用户裁决后再动 `composition.py`。**

## 三、确定性与真实两层证据分开

- `tests/integration/test_codex_interaction_capabilities.py`（11 条，替身服务端）：
  证明**上层按既定协议形状收发**——能力声明真的发出去了、原生请求用同一个 id 回包、
  elicitation 走同一入口但形状不同、嵌套 item 可观测、进程退出会唤醒挂起请求。
  它**不**证明真实二进制支持其中任何一项。
- `scripts/probe_codex_capabilities.py`：对真实二进制跑同样的问题。
- 两层的分工写进了探针与测试文件的头注释，避免以后有人拿一层的绿去当另一层的证据。

## 四、交付物

| 路径 | 变更 |
|---|---|
| `zhiyuan-agent/scripts/probe_codex_capabilities.py` | 新增，能力探针 |
| `zhiyuan-agent/tests/integration/test_codex_interaction_capabilities.py` | 新增，协议形状回归 |
| `zhiyuan-agent/tests/fixtures/codex/fake_app_server.py` | 扩展：带 id 的 server request、嵌套 MCP item、进程退出 |
| `zhiyuan-agent/tests/fixtures/mcp/eliciting_server.py` | 新增，会发 elicitation 的 MCP fixture |
| `zhiyuan-agent/app/harness/client.py` | `initialize(..., capabilities=None)` |
| `zhiyuan-agent/app/harness/codex.py` | 透传 capabilities，保留 `initialize_result` |
| `zhiyuan-agent/app/config.py` | 新增 `user_input_mode` |
| `zhiyuan-agent/tests/integration/test_gateway_composition.py` | 新增两条配置形状/启动回归 |

**未改动**：`app/gateway/composition.py`（过程见第七节）。

## 五、elicitation：没测到，不是"不支持"

两种形态都试了，都不能作为"不支持"的证据：

- **legacy**（服务端主动发 `elicitation/create`）：可复现。codex **自己回了
  `{"action":"decline"}`**，客户端从头到尾没收到 `mcpServer/elicitation/request`
  （`serverRequests: []`）。考虑到我们声明的是 `openai/standard-form-input`
  而不是 legacy 的 `openai/form`，这个"拒收"**可能就是正确行为**，不算缺陷。
- **modern**（`resultType:"input_required"` + `inputRequests`）：报
  `Unexpected response type`。查了 codex 自己的测试服务端，现代形态要求
  `params._meta` 里带协商好的 `io.modelcontextprotocol/protocolVersion`，
  而本 fixture 没有协商现代协议版本——**这是夹具的错**，故记 `not_run`。

下一步（不属 A1）：让 fixture 协商现代 MCP 协议版本后重测；在此之前，
UI 侧不要把 MCP form 当成可用能力规划。

## 六、验收命令与原始结果

```
cd zhiyuan-agent
.venv/bin/python -m pytest tests/ -q                      # 基线核对
# 2 failed, 1741 passed, 42 skipped
# 两条 failed 与台账基线逐字同名（test_dialog_quality_gate、test_ops_release_smoke），
# 无新增；passed 由 1730 增至 1741（+11 = 本任务新增）

CODEX_APP_SERVER_BIN=<bin> .venv/bin/python -m pytest \
  tests/integration/test_codex_interaction_capabilities.py \
  tests/integration/test_gateway_composition.py \
  tests/integration/test_codex_app_server_poc.py -q       # 34 passed

DEEPSEEK_API_KEY=<key> .venv/bin/python scripts/probe_codex_capabilities.py \
  --bin <bin> --source-commit 5c5308f --real-model \
  --model deepseek-flash --model-provider deepseek \
  --provider-base-url https://api.deepseek.com --provider-env-key DEEPSEEK_API_KEY \
  --config features.default_mode_request_user_input=true \
  --config tools.experimental_request_user_input.enabled=true \
  --mcp-server tests/fixtures/mcp/codex_metadata_server.py
# 退出码 0；6 passed / 1 not_run

# 工具面（单独一条，当前预期为 failed）
.venv/bin/python scripts/probe_codex_capabilities.py \
  --bin <bin> --require-disabled shell_tool,unified_exec,browser_use,computer_use,in_app_local_automation \
  --skip requestUserInput --skip elicitation
# featurePolicy=failed, stillEnabled=全部五项, 退出码 1
```

密钥只以环境变量名出现在探针参数里，报告与代码中不含密钥值。

## 七、一次误判与更正（留给复核）

过程中我一度认定 `build_codex_command` 发出的 `--config` 值是无效的，并改了代码。
**这个结论是错的**：原实现用的是 `command=`（合法 TOML 内联表），我手写验证输入时
写成了 `{"command": ...}`（JSON），等于在自己造的副本里制造了那个 bug 再把它"修"掉。
实测原始实现：TOML 可解析、真实二进制握手成功。已把 `composition.py` **逐字还原**，
并在新测试的注释里写明它防的是什么（JSON 风格的值会被 `-c` 退化成字面字符串，
二进制启动时才以 `expected struct RawMcpServerConfig` 退出）。

方法论：**验证"这个检查能失败"时，失败输入必须从生产者那一侧取，不能手抄。**
手抄会在副本里悄悄修掉要验的缺陷——这与台账里"桩的形状要从生产者取"是同一条。

## 八、未验证项（不得据此声称已具备）

- elicitation 的现代形态（第五节）。
- 官方文档 `https://developers.openai.com/codex/app-server/` 本轮仍未获取（此前 403）。
- 域内 MCP（`zhiyuan_domain` 八个只读工具）对真实二进制的工具清单：本任务用的是
  测试 fixture。**后续已补**：真实二进制现在看到 `zhiyuan_domain` 的 8 个工具且每个
  带 `readOnlyHint: true`（过程中修掉两个阻断缺陷，见 A2 报告的「生产 MCP 链路」一节）。
  越权工具行为验收仍按计划属 B7。
- 三个 provider 之外的组合（`gpt-6-astra`/clawd）未探针——结论不外推。

## 九、证据边界声明

本报告的"passed"均指**协议层可收发**，不指产品功能可用：没有一条覆盖
"用户看到什么"。页面级验收按计划归 C4。
