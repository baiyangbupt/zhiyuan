# 浏览器 e2e 的容器镜像（Task C4 的环境适配）。
#
# 为什么要有它 ✓：`node:20` 里**没有** chromium 的系统依赖 ✗，而 `playwright install --with-deps`
# 会在**每次运行**时跑一遍 apt ✗✗——这台网络到 `deb.debian.org` 极慢/被墙 ✗（实测卡了 47 分钟 ✗）。
# 烘进镜像后：apt 只付一次 ✓，且走**阿里云 Debian 源**（本机可达 ✓）。
#
# 用法（runner 会自动用，见 scripts/run-codex-e2e-in-container.sh ✓）：
#   docker build -t zhiyuan-e2e-playwright:1.55.0 ops/e2e
FROM docker.m.daocloud.io/library/node:20

ARG PLAYWRIGHT_VERSION=1.55.0

# apt 走阿里云 ✓（`deb.debian.org` 在这个网络里基本不可用 ✗）。
RUN set -eux; \
    . /etc/os-release; \
    # 注意 ✓：bookworm 用的是 **deb822** 格式（`/etc/apt/sources.list.d/debian.sources` ✓），
    # 只改老的 `sources.list`/`*.list` 会**静默无效** ✗（第一版就漏了这个 ✗，注释说了做而没做 ✓）。
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi; \
    sed -i "s|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g" \
        /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcairo2 libcups2 libdbus-1-3 \
        libdrm2 libgbm1 libglib2.0-0 libnspr4 libnss3 libpango-1.0-0 libx11-6 libxcb1 \
        libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 xvfb \
        fonts-noto-color-emoji fonts-unifont libfontconfig1 libfreetype6 xfonts-scalable \
        fonts-liberation fonts-ipafont-gothic fonts-wqy-zenhei fonts-tlwg-loma-otf fonts-freefont-ttf; \
    rm -rf /var/lib/apt/lists/*

# 依赖与浏览器一并烘进去 ✓（含 fontconfig 缓存 ✓）。
RUN set -eux; \
    mkdir -p /opt/e2e; cd /opt/e2e; \
    npm init -y >/dev/null; \
    npm i -s --no-audit --no-fund "@playwright/test@${PLAYWRIGHT_VERSION}"; \
    npx playwright install chromium

WORKDIR /opt/e2e
