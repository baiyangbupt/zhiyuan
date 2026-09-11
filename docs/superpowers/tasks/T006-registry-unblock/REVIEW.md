---
task: T006
verdict: ACCEPTED
reviewer: 设计会话（Claude Opus 5）
reviewed_at: 2026-09-11
---

# T006 回收判定

## 一、判定

`ACCEPTED`。改动两行，效果可现场验证：本地 codex 环境从"镜像拉不下来，compose 起不来"变成"两个容器 healthy 且已连续运行 12 小时"。

一条跟进项（供应链，见第四节），不阻塞。

## 二、自行重跑的验收（不采信报告输出）

### 镜像名解析

```
docker.m.daocloud.io/library/mysql:8.0
docker.m.daocloud.io/library/redis:7-alpine
config-exit=0
```

### 容器现状（reset→start 之后 12 小时）

```
zhiyuan-codex-local-mysql-1 | docker.m.daocloud.io/library/mysql:8.0        | Up 12 hours (healthy)
zhiyuan-codex-local-redis-1 | docker.m.daocloud.io/library/redis:7-alpine   | Up 12 hours (healthy)
```

不只是"当时起来了"——健康检查连续 12 小时没掉，比报告里的 `Up 17 seconds (healthy)` 更有说服力。

### 本地镜像摘要与报告拉取日志比对

```
docker.m.daocloud.io/library/redis  7-alpine  sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf
docker.m.daocloud.io/library/mysql  8.0       sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b
```

与报告第三节 `docker pull` 输出的 `Digest:` 行逐字符一致。报告没有伪造拉取记录。

### 全量单测

本任务只改 compose 文件，不入单测路径。报告的 `2 failed, 1700 passed, 34 skipped` 与基线一致（+1 为 T005 新增用例），我在 T005 复核时已独立重跑确认。

## 三、实现质量评审

**改法正确。** 两个 `image:` 字段改成 `${VAR:-<镜像源地址>}`，默认值即可达地址，`scripts/codex-local-infra.sh` 一行不改。报告第六节第 2 条把"多了一层环境变量"列为偏离——但这层是对的：把镜像源写死在 compose 里，换环境的人只能改文件；留覆盖位，换环境的人改 env 即可。接受。

**没有去动 `/etc/docker/daemon.json`，没有重启 daemon。** 这是本次最值得肯定的克制。宿主机上另有 4 个容器在跑（其中两个已连续运行 15 个月），重启 daemon 会把它们全部打断。报告第八节第 4 条明确记录了"未触碰"。

**诊断先于修改。** 六个候选源逐个探测、给出原始状态码，再拿改动前的失败现场（`registry-1.docker.io` `context deadline exceeded`）做对照，然后才改。这正是我在上一轮判定里要求的——先证明症状，再改。

**纠正了此前一条陈旧记录。** 之前记的阻塞是"Docker 环境不可用"，实测 daemon 完全正常，不通的只是 `registry-1.docker.io` 这一个地址。报告第八节把 `daemon.json` 里已配的阿里云个人版 CR 也列了（返回 401，即可达），说明镜像源配置本身生效、只是 compose 里的裸名走了默认 Hub。定位准确。

## 四、跟进项（不阻塞）

**镜像来自第三方镜像站，摘要无法与 Docker Hub 交叉验证。**

`docker.m.daocloud.io` 是社区镜像站，不是 Docker 官方。当前网络下 `registry-1.docker.io` 不可达，所以**没有办法核对这两个摘要是否等于 Docker Hub 上 `library/mysql:8.0` 的官方摘要**——我试不了，报告也没有试。

影响面有限：这套 compose 只用于本地 codex 开发环境（`docker-compose.codex-local.yml`，配套 `.local/codex-local/` 里的随机 root 密码），不进生产。但这条要明确落账，避免哪天有人把同样的镜像源复制进生产编排。

建议（排期低）：等某次有能连 Hub 的网络环境时，把两个摘要与官方比一次，比中了就把 compose 里的 tag 改成 `@sha256:` 固定摘要。固定摘要之后，镜像源换谁都不影响内容可信度。

## 五、边界核对

`git status` 中属于本任务的改动只有 `docker-compose.codex-local.yml` 一个文件，与报告声明一致。其余变更分属 T005 / T007 / P1a，已各自单独复核。

`.local/codex-local/`（含随机生成的 MySQL root 密码）在 `.gitignore:54` 已忽略，本次未被带进暂存区。未 commit，符合协议。

**关于"本任务没有任务书"**：报告第六节第 1 条属实，T006 / T007 都是我口头派发、没写 `TASK.md`。这是我的流程疏漏——`README.md` 第七节写的是"报告存在且状态词合法"才进复核，没说没有任务书时怎么判边界。实现方的处理是对的（按 LEDGER 标题取范围、把这一点写进偏离节）。已在 `README.md` 补充：口头派发的任务，复核时以 LEDGER 标题为边界依据，且报告必须声明这一点。
