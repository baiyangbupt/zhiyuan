# Codex Local Stack

`scripts/codex-local-infra.sh` prepares disposable MySQL/Redis containers first.
It uses `docker-compose.codex-local.yml`, the Compose project
`zhiyuan-codex-local`, named volumes `zhiyuan_codex_local_mysql_data` and
`zhiyuan_codex_local_redis_data`, and host ports `13306/16379`. It does not
reuse the root Compose file or its volumes.

```bash
bash scripts/codex-local-infra.sh start
export CODEX_LOCAL_SERVER_CONFIG="$PWD/.local/codex-local/application-codex-local.yml"
export CODEX_LOCAL_DATASET=private-resettable
export CODEX_LOCAL_CODEX_HOME=/absolute/path/to/isolated-codex-home
bash scripts/start-codex-local.sh
```

The command creates `.local/codex-local/infra.env` and
`.local/codex-local/application-codex-local.yml` with mode `0600`. The generated
Spring file points at the disposable database and Redis ports and contains
disabled external-service placeholders. It is the `CODEX_LOCAL_SERVER_CONFIG`
input for the application stack below. `stop` retains data; `reset` removes
only this project and its two named volumes.

The launcher passes `CODEX_LOCAL_REVIEW_MODE` (default `active`) to the backend
as `planning.review.mode`; set it to `paused` only for the affected local
environment after the Java/Agent/Web review-consumer changes are deployed. The
paused policy does not run old review rules, returns `reviewState.status=paused`
with empty findings/summary, and still allows user-goal/score/plan actions with
their real postconditions.

The generated local-only file also persists `demo.prepare-type-fallback: "PREDICT"`.
This keeps demo score updates on the available prediction data when the upstream
province policy has switched to `VOLUNTEER` before that dataset is ready. It is a
fallback only: explicitly requested or already stored modes are not overwritten,
and production profiles still default to province policy. The selected mode is
frozen into the score confirmation payload together with the previewed scores.
Set `CODEX_LOCAL_PREPARE_TYPE_FALLBACK=VOLUNTEER` when generating a local file to
test that mode, or set it to an empty string to disable the fallback. Private
configurations supplied separately must declare the setting themselves; do not
depend on a one-off `/tmp` restart script carrying the flag. Existing processes
must be restarted to load a changed Spring configuration.

`scripts/start-codex-local.sh` starts a fresh local validation stack on ports
`18290` (Java), `18291` (Agent), `18292` (Rank), and `3201` (Web). It is a
separate path from `scripts/start-all.sh`: it never adopts a listener, changes
an existing PID file, or uses the default shared local configuration.

The script accepts only a private, resettable Java configuration. Put that file
outside the repository, or below the ignored `.local/codex-local/` directory,
point it at an isolated MySQL/Redis dataset, and declare it explicitly:

```bash
export CODEX_LOCAL_SERVER_CONFIG=/absolute/path/application-codex-local.yml
export CODEX_LOCAL_DATASET=private-resettable
export CODEX_LOCAL_CODEX_HOME=/absolute/path/codex-home

bash scripts/start-codex-local.sh
```

`CODEX_LOCAL_CODEX_HOME` contains the intended Codex App Server authentication
and model catalog. It is intentionally explicit so the local validation stack
cannot silently use a developer's global Codex configuration. The command does
not print the contents of either private directory.

The model/provider and the harness are separate settings. The business
`CODEX_LOCAL_CODEX_HOME/config.toml` selects `model`, `model_provider` and its
Responses-compatible endpoint. DeepSeek is supported through that custom
provider configuration; the harness does not require an OpenAI model or the
developer's ChatGPT login. `LLM_*` settings belong to the separate legacy Python
agent and do not select the business Codex App Server model.

Use a project-specific Codex installation as well as a separate home directory.
The Gateway launches `codex app-server --stdio` as its child and owns its
lifecycle; a manually started global App Server is not required. Domain MCP is
another child started by that business App Server. Keep credentials in the
business provider's environment or private credential source, independently of
the Codex session used to develop this repository.

### Harness compatibility and tool policy

The business runtime checks `CODEX_APP_SERVER_EXPECTED_VERSION` (default
`0.165.0`) against `CODEX_APP_SERVER_BIN --version` before every process
generation starts. Set `CODEX_APP_SERVER_BIN` to the deployment's intended
executable. Upgrading a global CLI does not authorize a business runtime upgrade:
validate the new protocol and skill-loading path before changing the expected
version. A mismatch stops startup or recovery.

After initialize, and before creating a business thread, the runtime reads the
effective configuration. It rejects additional enabled MCP servers and inherited
notification commands. Shell, hosted web search, apps, browser/computer use,
image tools, hooks, plugins and subagents are disabled by explicit overrides.
Managed settings that prevent these overrides make startup fail closed.

Planning skills do not require plugin installation or shell reads in this mode.
The `zhiyuan_domain` MCP server exposes the packaged skills and their Markdown
references as `skill://zhiyuan/<skill>/SKILL.md` resources. Arbitrary paths and
resources outside the packaged root are rejected. Native terminal sessions can
still use their own configuration; these overrides apply to the business child.

Tool progress remains live. Raw model prose is withheld until the Gateway's
business/reference checks finish, then the turn worker publishes the final
answer. Reference validation checks identity, scope and freshness; it does not
prove the semantic correctness of every sentence generated by a model.

The Java configuration must contain the connection settings for a disposable
dataset. The launcher overrides only the per-run wiring below, so the four
processes always point to the same isolated port group:

```yaml
server:
  port: 18290
agent:
  zhiyuan:
    url: http://127.0.0.1:18291
volunteer:
  rank:
    url: http://127.0.0.1:18292
```

The actual database and Redis credentials remain in the private file. Do not
use any configuration below `zhiyuan-server/src/main/resources`, an online
configuration, or a shared test dataset as the input. The launcher rejects
repository defaults and tracked files, then fails before it builds or starts
anything when the required declaration is missing.

For a backend/Agent verification without Next.js:

```bash
bash scripts/start-codex-local.sh --skip-web
```

By default the script builds a current Java jar. Use `--skip-build` only after
building `zhiyuan-server` yourself. The jar is copied into the run directory
before launch, so later Maven builds cannot invalidate a running JVM's nested
jar entries. It writes logs, PID records, the binding
registry, and health responses to a fresh `.runtime/codex-local-*` directory.
The ready message prints that directory and the exact stop command:

```bash
bash scripts/stop-codex-local.sh /root/dev/zhiyuan/.runtime/codex-local-...
```

`stop-codex-local.sh` only signals PIDs that it recorded and whose command line
still matches this repository and carries the exact run-directory marker set
by the launcher. It does not search for or stop unrelated listeners.

Once the stack is ready, the direct WebSocket client can exercise a read-only
turn without the browser:

```bash
cd zhiyuan-agent
.venv/bin/python scripts/local_ws_client.py \
  --url ws://127.0.0.1:18291/ws/chat \
  --tenant-id 1 \
  --session-id 10001 \
  --user-id 10001 \
  --message "Explain the available candidates."
```

The script configures `GATEWAY_MODE=codex_readonly`, a per-run binding registry,
`INTERNAL_SERVICE_URL`, and `RANK_SERVICE_URL`. Codex starts the domain MCP
server as a child of the Agent process; no persistent MCP process is launched.
The preflight does not prove that a supplied database is resettable. That is an
operator-owned property represented by `CODEX_LOCAL_DATASET=private-resettable`.
Real Pending/CAS HTTP E2E must run only after that private dataset is prepared.

## 访问面：本地模式与公开测试模式（Task C2）

默认 Web 仅监听 `127.0.0.1:3201`，其他机器不能通过服务器内网 IP 直接访问。
需要局域网浏览器验收时，在现有启动参数上增加 `--web-host 10.218.4.10`，或设置
`CODEX_LOCAL_WEB_HOST=10.218.4.10`。仅允许显式 RFC1918 私有 IPv4，拒绝通配地址和公网 IP；
不改变默认回环模式，也不改变公开测试模式的 HTTPS 约束。

此时 Web 监听指定内网地址；浏览器 WebSocket 走同源 `/ws/chat`，由 Next 转发到回环 Agent，
并自动把该 Web origin 加入票据/连接白名单。Java、Agent、Rank 仍只监听回环，内部 API
路径仍由代理守卫拒绝。不要仅修改 Next 的监听地址、却保留浏览器的回环 WebSocket override。

只检查解析结果、不启动或重启服务：

```bash
bash scripts/start-codex-local.sh --web-host 10.218.4.10 --print-access-env
```

隔离栈有两套**访问面**口径，由 `CODEX_LOCAL_ACCESS_MODE` 选择 ✓：

| 模式 | WebSocket | outer API |
|---|---|---|
| `local`（默认 ✓） | `NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE=ws://127.0.0.1:$AGENT_PORT` ✓ | `CODEX_LOCAL_OUTER_API_BASE_URL`，未配则用生产默认 ✓ |
| `public-test` | **清空** override ✓——浏览器按 `window.location` 派生**同源 wss** ✓ | **必须显式**给受控测试源 ✓；缺了就拒 ✓，也不许指向 origin 自己 ✓ |

公开测试模式还要给 `CODEX_LOCAL_PUBLIC_ORIGIN=https://<host>` ✓：**必须是无路径、无凭证的 https origin** ✓，
否则启动前就失败 ✓。这些判据与守卫只有一份 ✓（`scripts/codex-local-access.sh` ✓，
`start` 与 `preflight` 共用 ✓）——两处各写一份早晚自相矛盾 ✗。

看"实际会用的值"而不启动任何东西：

```bash
CODEX_LOCAL_ACCESS_MODE=public-test \
CODEX_LOCAL_PUBLIC_ORIGIN=https://test-wwww.gaotuzhiyuan.com \
CODEX_LOCAL_OUTER_API_BASE_URL=https://<受控测试源> \
bash scripts/start-codex-local.sh --print-access-env
```

反向代理的位置块见 `ops/nginx/codex-test.locations.conf` ✓（`map`/`log_format` 属 http 层 ✓，
其余放现有 HTTPS server 内 ✓，部署前 `nginx -t` ✓）；公开域冒烟：
`bash scripts/smoke-codex-public.sh --origin https://<host> [--base-path /]` ✓
（无票据时只跑匿名检查并如实写 `authenticated=not_run` ✓）。

安全口径：**只放行对话需要的精确路径** ✓——`/inner/`、`/internal/`、`/admin/`、`/debug/` 一律 404 ✓；
Java/Agent/Rank 与两个数据端口都只监听回环 ✓。

## 验收环境与人工清单（Task C3）

- 环境基线（四服务端口/版本 ✓、数据面共用实例的提示 ✓✓、DNS/TLS 阻塞项 ✓）：
  `docs/validation/codex-native-environment.md` ✓
- 人工浏览器清单（本地 → 公开域 → 收尾 ✓，每步写明要记什么 ✓，禁止记录原始凭证 ✗）：
  `docs/validation/codex-native-browser-checklist.md` ✓
- 合成数据的建/清：

  ```bash
  # 看要建什么（默认 dry-run ✓，不写库）
  zhiyuan-agent/.venv/bin/python scripts/seed-codex-acceptance.py --run-id r1
  # 真写：必须指名实例 ✓（按"容器公布的 3306 == 要连的端口"核对 ✓）
  zhiyuan-agent/.venv/bin/python scripts/seed-codex-acceptance.py \
      --expect-instance zhiyuan-codex-local-mysql-1 --run-id r1 --apply
  # 只清本次 runId 建的行 ✓（删除范围只来自 fixture-ids.json ✓）
  zhiyuan-agent/.venv/bin/python scripts/seed-codex-acceptance.py \
      --reset .runtime/codex-acceptance/r1/fixture-ids.json --apply
  ```

  **注意** ✓：本机这套 MySQL/Redis **同时被跑着的共享栈用着** ✗——reset 永远只按 fixture
  里记录的 id 删 ✓，绝不整栈重置 ✓。
