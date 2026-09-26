#!/usr/bin/env bash
# 在**容器里**跑 zhiyuan-web 的 Playwright e2e（Task C4 的环境适配）。
#
# 为什么必须这样：本机是 CentOS 7 / **glibc 2.17** ✗，而 Playwright 的 chromium 要
# **GLIBC 2.18 / 2.25** ✗✗——宿主**根本起不来** ✓（探明过程与读数见
# `docs/validation/codex-native-environment.md` §4.1 ✓）。容器自带 glibc ✓，宿主零改动 ✓。
#
# 三条硬约束（都为了"别碰宿主、别碰生产" ✓）：
#   1. `--network host` ✓：容器要连宿主回环上的服务（3201/18290/18291 ✓）；
#   2. 仓库**只读**挂载 ✓（`--install` 除外 ✓，那一档才允许它写 lockfile ✓）；
#   3. **不给任何默认 origin** ✗：`ZHIYUAN_E2E_ORIGIN` / `ZHIYUAN_E2E_SESSION_URL` 必须显式给 ✓
#      （config 自己也会抛 ✓）；镜像走 `docker.m.daocloud.io` ✓（Docker Hub 本体不可达 ✗）。
#
# 用法：
#   ZHIYUAN_E2E_ORIGIN=http://127.0.0.1:3201 \
#   ZHIYUAN_E2E_SESSION_URL=/assistant-pc/sessionDetailV2 \
#     bash scripts/run-codex-e2e-in-container.sh --project contract
#
#   # 首次同步依赖（**唯一**允许写仓库的一档 ✓：它只执行 `npm i -D @playwright/test@<pin>`）
#   bash scripts/run-codex-e2e-in-container.sh --install
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
WEB_DIR="$ROOT_DIR/zhiyuan-web"
IMAGE="${CODEX_E2E_IMAGE:-docker.m.daocloud.io/library/node:20}"
PINNED_TEST_VERSION="${CODEX_E2E_PLAYWRIGHT_VERSION:-1.55.0}"
PROJECT="contract"
MODE="run"
# 浏览器缓存：宿主那份与容器内是**同一个二进制** ✓（能不能跑取决于 glibc ✓——容器里能跑 ✓），
# 所以挂进来复用 ✓，重复跑不用再下 ~150MB ✗。
BROWSER_CACHE="${CODEX_E2E_BROWSER_CACHE:-$HOME/.cache/ms-playwright}"

usage() {
    cat <<'EOF'
Usage: bash scripts/run-codex-e2e-in-container.sh [--install] [--project contract|real] [-- <playwright args>]

  --install          只同步依赖：容器内 npm i -D @playwright/test@<pin>（会改 package.json/lockfile）
  --project NAME     contract（默认）| real
  --                 其余参数原样转给 npx playwright test

Required env (run mode):
  ZHIYUAN_E2E_ORIGIN       页面 origin（例如 http://127.0.0.1:3201）
  ZHIYUAN_E2E_SESSION_URL  会话路由（例如 /assistant-pc/sessionDetailV2）
EOF
}

EXTRA=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) MODE="install"; shift ;;
        --project) [[ -n "${2:-}" ]] || { echo "--project requires a value" >&2; exit 2; }; PROJECT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        --) shift; EXTRA=("$@"); break ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [[ "$PROJECT" != "contract" && "$PROJECT" != "real" ]]; then
    echo "unknown project: $PROJECT（只认 contract|real ✓）" >&2
    exit 2
fi

if [[ "$MODE" == "run" ]]; then
    # **不给默认值** ✗：缺了就直接拒 ✓（同 config 的口径 ✓）。
    [[ -n "${ZHIYUAN_E2E_ORIGIN:-}" ]] || { echo "缺少 ZHIYUAN_E2E_ORIGIN（拒绝默认打生产 ✗）" >&2; exit 2; }
    [[ -n "${ZHIYUAN_E2E_SESSION_URL:-}" ]] || { echo "缺少 ZHIYUAN_E2E_SESSION_URL" >&2; exit 2; }
fi

mkdir -p "$BROWSER_CACHE"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "本地没有镜像 $IMAGE ✓ → 拉取中（daocloud 镜像源 ✓；Docker Hub 本体不可达 ✗）"
fi

# 依赖准备：**在容器里**装 ✓（宿主 node 是 20 ✓ 但 glibc 太老 ✗，装出来的东西也跑不动 ✓）。
# `--install` 档挂**可写** ✓（它唯一要做的事就是同步 package.json/lockfile ✓）；
# run 档挂**只读** ✓（跑测试不该改仓库 ✓）。
if [[ "$MODE" == "install" ]]; then
    MOUNT=(-v "$WEB_DIR:/work")
    echo "== 依赖同步（唯一允许写仓库的一档 ✓）：@playwright/test@$PINNED_TEST_VERSION =="
    docker run --rm --network host "${MOUNT[@]}" -v "$BROWSER_CACHE:/root/.cache/ms-playwright" -w /work "$IMAGE" bash -lc '
        set -e
        npm i -D --no-audit --no-fund "@playwright/test@'"$PINNED_TEST_VERSION"'"
        npx playwright install --with-deps chromium >/dev/null
        echo "✓ 依赖与浏览器就绪（容器内）"
    '
    exit 0
fi

echo "== 容器内跑 e2e（project=$PROJECT，origin=$ZHIYUAN_E2E_ORIGIN）=="
docker run --rm --network host \
    -v "$WEB_DIR:/work:ro" \
    -v "$BROWSER_CACHE:/root/.cache/ms-playwright" \
    -e "ZHIYUAN_E2E_ORIGIN=$ZHIYUAN_E2E_ORIGIN" \
    -e "ZHIYUAN_E2E_SESSION_URL=$ZHIYUAN_E2E_SESSION_URL" \
    -e "ZHIYUAN_E2E_AUTH_STATE=${ZHIYUAN_E2E_AUTH_STATE:-}" \
    -w /opt/e2e "$IMAGE" bash -lc '
        set -e
        # 只读挂载 ✓ → 依赖与产物都落在容器自己的层里 ✓（`--install` 已把版本写进 package.json ✓）。
        mkdir -p /opt/e2e && cd /opt/e2e && npm init -y >/dev/null 2>&1
        npm i -s --no-audit --no-fund @playwright/test@'"$PINNED_TEST_VERSION"' >/dev/null 2>&1
        npx playwright install --with-deps chromium >/dev/null 2>&1
        # **把它们拷进来跑** ✓：`/work` 是只读的 ✓，而 Playwright 既要解析 `@playwright/test`
        # （从配置所在目录往上看 ✗）又要写 `test-results/` ✗——在原地跑两头都做不到 ✓。
        cp -r /work/playwright.config.ts /work/tests /opt/e2e/
        exec /opt/e2e/node_modules/.bin/playwright test --project='"$PROJECT"' \
            --output=/opt/e2e/test-results "$@"
    # `${EXTRA[@]}` 在**空数组 + `set -u`** 下会报 unbound ✗（bash 4.2 ✓ 本机就是 ✓）——
    # 必须写成"有才展开"的形式 ✓。
    ' bash ${EXTRA[@]+"${EXTRA[@]}"}
