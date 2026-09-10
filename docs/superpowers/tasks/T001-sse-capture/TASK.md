# 任务 A：采集 DeepSeek `/responses` 流式断开现场

> 指派：DeepSeek 实现会话
> 来源计划：`docs/superpowers/plans/2026-09-10-对话执行引擎推进计划修订.md` 的 P0
> 类型：诊断数据采集。**你只负责采集，不负责修复**

---

## 一、目标

搭建一个透传代理，夹在 Codex App Server 与 DeepSeek 之间，抓取复杂回合中 SSE 流被断开的原始现场数据，落盘供分析。

一句话验收：拿到至少 3 次复现的完整 dump，能看出流在**哪个 SSE 事件之后**、**距请求开始多少秒**、**以何种方式**终止。

---

## 二、你需要知道的背景（你的会话没有这些上下文）

本仓库 `/root/dev/zhiyuan` 是一个高考志愿咨询对话系统。其中 `zhiyuan-agent` 用 OpenAI 开源的 codex 作为对话引擎宿主，通过 `codex app-server --stdio` 与之通信，模型接的是 DeepSeek。

当前阻塞：简单回合能跑通，但复杂回合（多工具调用、长上下文）中，Codex App Server 请求 DeepSeek `/responses` 时会在 `response.completed` 事件到达之前流断开，连续重试 5 次后失败。

这个阻塞卡住了整个项目的质量验收。但**目前没有人看到过断开时的原始字节流**，所以无法判断是 DeepSeek 上游主动关闭、codex 侧解析异常、还是超时截断。你的任务就是把这个现场抓出来。

---

## 三、已核实的环境事实（不要重新验证，直接用）

| 事实 | 值 |
|---|---|
| Rust 工具链 | `cargo 1.72.1`，**但 codex-rs 要求 1.95.0 + edition 2024** |
| 结论 | **不要尝试 `cargo build` 编译 codex 的 responses-api-proxy，一定失败**。用 Python 写代理 |
| 无 `rustup` | 不要去装 Rust，那不是本任务的路 |
| Python 环境 | `/root/dev/zhiyuan/zhiyuan-agent/.venv/bin/python`，3.10.14，已装 `aiohttp` 和 `httpx` |
| 系统 python3 | 3.6.8，**不要用**，用上面的 venv |
| codex 二进制 | `/root/.nvm/versions/node/v20.20.2/bin/codex`，版本 `codex-cli 0.154.0` |
| DeepSeek 端点 | `https://api.deepseek.com` 可达（未带鉴权时返回 401） |
| 现有 codex 配置 | `/root/dev/zhiyuan/.codex-semantic-home/config.toml`，其中 `[model_providers.deepseek]` 的 `base_url = "https://api.deepseek.com/"` |
| 复现脚本 | `/root/dev/zhiyuan/zhiyuan-agent/scripts/codex_semantic_smoke.py` |

---

## 四、步骤

### 步骤 1：写透传代理

新建 `zhiyuan-agent/scripts/sse_capture_proxy.py`。

**必须满足的行为约束**（这些直接决定数据有没有用）：

1. **路径无关**：接受任意路径的 POST，转发到 `https://api.deepseek.com` + 收到的相同路径。不要硬编码 `/v1/responses`，因为 codex 如何拼 URL 尚未确认，路径无关可以免去猜测。
2. **逐块透传，绝对不缓冲**：收到上游一个 chunk 就立刻写给下游客户端。**如果你缓冲整个响应再转发，就会掩盖断流现场，整个任务作废**。
3. **原样转发 header**：除 `Host` 外全部透传，尤其 `Authorization`。不要改写 `Content-Type`、不要动 `Accept`。
4. **落盘内容**，每次请求一个独立文件（用递增序号或时间戳命名）：
   - 请求方法、完整路径、请求头（**`Authorization` 的值必须打码，只留前 8 位**）
   - 请求体全文
   - 每一个收到的 chunk：单调时钟相对时间戳（秒，精确到毫秒）+ chunk 原始字节的 repr 或 hex
   - 终止记录：三选一并明确标注
     - `CLEAN_EOF`（上游正常结束流）
     - `EXCEPTION`（记录异常类型全名和 str(异常)）
     - `TIMEOUT`（记录超时阈值）
   - 从请求发出到终止的总耗时
5. **不设短超时**：读超时至少 300 秒，避免代理自己先超时，把上游行为掩盖掉。

监听端口用 `18999`。落盘目录用 `/root/dev/zhiyuan/.runtime/sse-capture/`（不存在则创建）。

### 步骤 2：接入配置

复制一份 codex 配置用于抓包，**不要原地改** `.codex-semantic-home/config.toml`：

```bash
cp -r /root/dev/zhiyuan/.codex-semantic-home /root/dev/zhiyuan/.codex-capture-home
```

编辑 `/root/dev/zhiyuan/.codex-capture-home/config.toml`，把 `[model_providers.deepseek]` 的 `base_url` 指向本地代理（保持原来的路径尾部形态，只换 scheme+host+port）。`model_catalog_json` 里的绝对路径也要跟着改到新目录下的 `models.json`。

### 步骤 3：复现并采集

启动代理，然后设置 `CODEX_HOME=/root/dev/zhiyuan/.codex-capture-home`，用 venv python 运行 `scripts/codex_semantic_smoke.py`，跑**复杂场景**（完整历史查询、混合读写这两类；脚本的场景参数请自己读脚本的 `argparse` 部分确定怎么传）。

反复运行直到拿到**至少 3 次非 `CLEAN_EOF` 的终止记录**。如果跑了 10 次都是正常结束，如实报告"无法复现"，不要编造。

### 步骤 4：汇总

写 `/root/dev/zhiyuan/.runtime/sse-capture/SUMMARY.md`，一次运行一行的表格：

| 运行序号 | 场景 | 终止方式 | 总耗时(s) | 最后一个完整 SSE 事件的 `type` | chunk 总数 |

表格下方原样粘贴**最后 3 个 chunk 的原始内容**（每次失败运行各一组）。不要做解读和推断，只呈现事实。

---

## 五、陷阱（会让你白干的地方）

1. **缓冲会毁掉整个任务**。用 `aiohttp` 的 `resp.content.iter_any()` 或 `httpx` 的 `stream()`，不要用 `await resp.read()` / `resp.text`。
2. **不要尝试编译 codex-rs**。Rust 版本不满足，会浪费大量时间。
3. **不要改 `.codex-semantic-home/`**，那是现有语义烟测在用的目录，改坏了会连带破坏别的验证。用复制出来的 `.codex-capture-home`。
4. **不要把 `Authorization` 明文写进 dump 文件**。落盘前打码。
5. 如果 codex 因为 TLS 或证书拒绝连本地 HTTP 代理，如实报告，不要去关证书校验绕过——那会改变传输行为，抓到的就不是原始现场了。

---

## 六、验收

```bash
ls /root/dev/zhiyuan/.runtime/sse-capture/          # 有 dump 文件和 SUMMARY.md
grep -c "Authorization" /root/dev/zhiyuan/.runtime/sse-capture/*.log   # 出现的都必须是打码后的
```

`SUMMARY.md` 必须能回答：流在哪个 SSE 事件后停、距开始多少秒、终止方式是什么。

---

## 七、边界：不要做这些

- **不要试图修复断流问题**。定性和方案由设计会话负责。
- 不要修改 `app/` 下任何代码。
- 不要修改 `app/gateway/service.py`、`app/harness/` 下任何文件。
- 不要更换模型、不要改 `models.json` 里的模型参数。
- 不要给 codex 加重试逻辑。
- 不要把这次的临时目录和 dump 提交进 git。

---

## 八、汇报格式

只用以下四种状态之一开头，然后附 `SUMMARY.md` 全文：

- `DONE` — 拿到 ≥3 次失败现场，SUMMARY.md 已写完
- `DONE_WITH_CONCERNS` — 拿到了数据但有偏差（例如只复现了 1 次），说明偏差
- `BLOCKED` — 被环境挡住（说明具体是什么挡住的，附原始报错）
- `NEEDS_CONTEXT` — 任务书里有你无法自行确定的信息（说明缺什么）

不要在报告里给修复建议。
