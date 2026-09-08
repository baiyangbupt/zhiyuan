# Codex Shadow 回放运行手册

## 固定输入

Shadow runner 只接受仓库内的 `tests/fixtures/shadow/baseline_manifest.json`、`golden_cases.json` 和 `adversarial_cases.json`。fixture 中的 sessionId 必须是 `shadow-*`，禁止传入生产会话 ID。

## 执行

```bash
cd zhiyuan-agent
.venv/bin/python scripts/codex_shadow_replay.py \
  --manifest tests/fixtures/shadow/baseline_manifest.json \
  --golden tests/fixtures/shadow/golden_cases.json \
  --adversarial tests/fixtures/shadow/adversarial_cases.json \
  --output /tmp/zhiyuan-codex-shadow.jsonl
```

输出每个 case 一行 JSONL trace，包含 conversationId、turnId、threadId、snapshotVersion、skillName、tool/evidence 计数、writeAttempted、latencyMs 和 status。汇总中的四个硬门槛必须为零：未授权写、未知招生单元、无 Evidence 事实、跨会话 Proposal。若任一硬门槛非零，runner 以退出码 `2` 结束，CI 或发布脚本必须视为 `NO-GO`。Shadow 只比较，不自动宣称新引擎优于旧链路。

## 故障处理

fixture 校验失败、版本过期或 runner 试图访问生产 session 时立即 fail closed。协议或 binding 失败记录 NO-GO；不要把离线 fixture 结果解释为真实模型能力。
