# Codex 验收环境基线（Task C3）

> 用法：这是**验收环境的现状台账** ✓——跑 C3/C4 之前先读它 ✓。
> 口径：**只记实测** ✓；测不了的写成**具体阻塞项** ✗，**不用本地 curl 冒充公网通过** ✗
> （任务书 Task C3 最后一条点名要求 ✓）。测量时间：2026-09-26 ✓。

## 一、四服务与端口（本机实测 ✓）

| 服务 | 端口 | 现状 | 备注 |
|---|---|---|---|
| Java（共享栈 ✓） | 18090 | 在跑 ✓ pid 7010 | 只监听 `[::]`（**非**回环 ✗）|
| Agent（共享栈 ✓） | 18091 | 在跑 ✓ pid 27389 | `GATEWAY_MODE=codex_write` ✓ |
| Rank | 18092 | 在跑 ✓ gunicorn 6215/6217 | 只回环 ✓ |
| 前端（Next dev ✓） | 3001 | 在跑 ✓ pid 31168 | `APP_ENV=production` ✗ → `basePath=/assistant-pc` ✓，应用在 `/assistant-pc/...` ✓（`/` 本来就 404 ✗ 不是故障 ✓）|
| MySQL | 13306 | 在跑 ✓ `docker-proxy` | **`0.0.0.0` ✗**（见下「数据面」）|
| Redis | 16379 | 在跑 ✓ `docker-proxy` | 同上 ✗ |
| 隔离栈（C2 的那套 ✓） | 18290/18291/18292/3201 | **未启动** ✗ | 与本表其余端口不冲突 ✓ |

**健康探针** ✓：Java 的正确探针是 `/gaotu-assistant-bot/inner/ops/health` ✓
（隔离栈的启动脚本用的就是它 ✓）；**`/actuator/health` 恒 500 ✗，那不是故障** ✓——
别拿它当"服务挂了"的依据 ✗。

## 二、数据面：一套实例，被**两个栈**共用 ✗✓

- `zhiyuan-codex-local` compose 项目在跑 ✓（`zhiyuan-codex-local-mysql-1` / `-redis-1` ✓，
  镜像 `docker.m.daocloud.io/library/{mysql:8.0,redis:7-alpine}` ✓ 本机已有 ✓）。
- **正在跑的共享栈（18090 ✓）连的就是这一套** ✓（配置里指向 `127.0.0.1:13306` ✓）。
- 因此：**"隔离"隔离的是运行目录与服务 ✓，不是数据实例** ✗✗。这条直接影响 C3：
  - `scripts/seed-codex-acceptance.py` 的 reset **只删本次 runId 在 `fixture-ids.json` 里
    记录的 id** ✓✓——绝不能 `TRUNCATE`/按前缀删 ✗，否则会清掉共享栈的数据 ✓（包括
    本轮 P2 验证用到的会话 ✓）。
  - seed 前必须 `--expect-instance` 指名容器 ✓，并按**容器公布的 3306 端口 == 实际要连的端口**
    核对身份 ✓（`"private-resettable"` 这个字符串本身不是隔离证明 ✗，那只是数据源声明的名字 ✓）。
- 两个数据端口当前公布在 `0.0.0.0` ✗：`docker-compose.codex-local.yml` 已改成
  `127.0.0.1:` ✓（Task C2 ✓），但**跑着的容器是改之前起的** ✗——需要**栈的主人**重建容器才生效 ✓
  （不是本任务该做的动作 ✗）。

## 三、入口与网络（C3 的后半段 ✗）

| 检查（任务书点名 ✓） | 实测 |
|---|---|
| `getent hosts test-wwww.gaotuzhiyuan.com` | **解析不到** ✗ |
| `curl --fail --head https://test-wwww.gaotuzhiyuan.com/` | **Could not resolve host** ✗ |

**结论** ✓：公开测试模式的验收（C3 后两条复选框 ✓、以及 C2 报告里自标未验的第 2 条 ✗）
在本机**不具备条件** ✗——DNS 不通、TLS 无从验证、证书 SAN 无法核对 ✓。
按任务书要求，这里写成**具体阻塞项** ✓：**在拿到 DNS 解析与证书可用性之前，
不对公网域下的行为下任何"通过"结论** ✗。

## 四、解释器与工具（踩过的坑 ✓）

- **`/usr/bin/python3` 是 3.6** ✗：`from __future__ import annotations` 直接语法错 ✓。
  跑仓库脚本要用 `zhiyuan-agent/.venv/bin/python`（3.10 ✓）或 `.tools/python-3.10.14/bin/python3.10` ✓。
- `scripts/seed-codex-acceptance.py` 已加版本守卫 ✓（<3.10 先给一句人话再退出 ✓）。
  **但它还需要 `mysql-connector`** ✗：`zhiyuan-agent/.venv` 里**没有** ✗（那是回放脚本的坑 ✓），
  所以要么给 venv 装上 ✓，要么用一个专用 venv ✓（本次用的是
  `.tools/python-3.10.14` + `pip install mysql-connector-python` ✓）。
- **退出码别用管道吞** ✗✗：`cmd | tail` 之后的 `$?` 是 `tail` 的 ✓——本次因此把一次
  "模块找不到"的失败读成了成功 ✓（两次踩同一个坑 ✓）。要么先 `> log 2>&1` 再看 `$?` ✓，
  要么开 `set -o pipefail` ✓。
- **浏览器**：2026-09-26 探清 ✓（比"没有 chrome"更准确 ✓）：
  - 外网**通** ✓（`registry.npmjs.org` 200 ✓、`pypi.org` 200 ✓）→ 依赖**装得上** ✓；
  - `@playwright/test` 已装过一次 ✓（Node **20** ✓，见下）、chromium 也**下得下来** ✓（114 MiB ✓）；
  - **但 chromium 起不来** ✗✗：它要 **GLIBC 2.18 / 2.25** ✗，本机 CentOS 7 是 **2.17** ✗——
    这是**地板问题** ✓，不是缺包 ✓（缺的 3 个库 `libatk-bridge-2.0.so.0`／`libatspi.so.0`／
    `libxkbcommon.so.0` 已从阿里云 vault 取到 `/opt/pw-libs/usr/lib64` ✓，可删 ✓，
    **仍然过不去** ✗）；同理 **Node 22 在本机也跑不起来** ✗（要 GLIBC 2.27/2.28 ✗），
    能用的只有 Node **20.20.2** ✗——任务书那句"Node ≥ 22.14.0"**在本机无法满足** ✗。
  - 另：本机 yum 源与 `vault.centos.org` 都**已失效** ✗（CentOS 7 EOL ✓，403／无 baseurl ✓），
    要取老 RPM 只能走 `mirrors.aliyun.com/centos-vault/...` ✓。
  - **结论** ✗：C4 的浏览器自动化**不能在这台机器上做** ✗；可行路径是**换机器跑**
    （C3 清单本来就要求"从另一台设备/网络" ✓）或在**容器**里跑 ✓（docker 可用 ✓）。
  - 因装驱动而动的 `package.json`／`package-lock.json`／`yarn.lock` **已全部回滚** ✓
    （本机用不上 ✗，留着只会污染 lockfile ✓）；保留 `zhiyuan-web/tests/e2e/browser-smoke.mjs` ✓
    作为 C4 的入口冒烟 ✓。

### 4.1 **容器路线：已验证可用** ✓✓（2026-09-26）

宿主 glibc 太老 ✗ 但 **docker 可用** ✓，所以浏览器跑在容器里 ✓（宿主零改动 ✓、`docker rmi` 即回退 ✓）。
**实测通过的配方** ✓（`--network host` 让容器直连本机 127.0.0.1 的服务 ✓；仓库只读挂 ✓、
不在仓库里装任何东西 ✓）：

```bash
docker run --rm --network host \
  -v "$PWD/zhiyuan-web/tests/e2e/browser-smoke.mjs:/work/browser-smoke.mjs:ro" \
  -w /work docker.m.daocloud.io/library/node:20 \
  bash -lc 'npm init -y >/dev/null && npm i -s playwright \
            && npx playwright install --with-deps chromium >/dev/null \
            && node browser-smoke.mjs'
```

**实测读数** ✓：浏览器在容器内启动 ✓；`http://127.0.0.1:3001/assistant-pc/sessionDetailV2`
→ **200** ✓，标题 `高途AI志愿填报-登录` ✓、真渲染出登录页 ✓；
`http://127.0.0.1:18090/gaotu-assistant-bot/inner/ops/health` → **200** ✓、`status: UP` ✓；
控制台 error **0** ✓、失败请求 **0** ✓。

**注意** ✓：容器里跑的 playwright **版本与浏览器都是容器自己的** ✓（宿主那份已回滚 ✓）；
**Docker Hub 本体不可达** ✗，必须走 `docker.m.daocloud.io` 前缀 ✓。
- Docker daemon 可用 ✓，所需镜像本机已有 ✓（不需要联网拉取 ✓）。

## 五、当前可做 / 不可做

| 能做 ✓ | 不能做 ✗ |
|---|---|
| 起隔离栈（`codex-local-infra.sh` 已就绪 ✓，镜像齐 ✓） | 公网域下的任何验收（DNS ✗） |
| `seed-codex-acceptance.py` 建/清合成数据 ✓（runId 作用域**已在真库验过** ✓✓） | 在**宿主**上跑浏览器（glibc 2.17 ✗）——要跑就进容器 ✓ |
| **容器里跑浏览器** ✓✓（配方见 §4.1 ✓，已连通 3001/18090 ✓） | "另一台设备"的入口检查（无出口 ✗） |
| 四服务的健康/端口/版本登记 ✓ | 把上面的本地结论外推成公网通过 ✗ |
| 本地回环页面上的人工步骤**清单化** ✓ | — |
