import assert from 'node:assert/strict';
import test from 'node:test';

import { extractStreamMessage } from './streamText.mjs';

// 真帧形状（2026-10-06/07 事件流里摘的真实增量拼接样本）
const REAL_SAMPLE =
  '{"responseType": "text", "message": "好，按你说的记：浙江考生，走第一段，2026年高考，' +
  '六科成绩——语文112、数学125、外语118、物理85、化学86、生物84，总分610。", ' +
  '"limitations": [], "conversationAction": null}';

test('完整闭合的 JSON：取出 message 全文', () => {
  assert.equal(
    extractStreamMessage(REAL_SAMPLE),
    '好，按你说的记：浙江考生，走第一段，2026年高考，六科成绩——语文112、数学125、外语118、物理85、化学86、生物84，总分610。'
  );
});

test('增量前缀：截断在任何位置都能给出已可读的人话前缀（且不包含 JSON 语法字符）', () => {
  for (let cut = 40; cut <= REAL_SAMPLE.length; cut += 7) {
    const prefix = extractStreamMessage(REAL_SAMPLE.slice(0, cut));
    assert.ok(!prefix.includes('"responseType"'), `cut=${cut} 泄漏了字段名`);
    assert.ok(!prefix.includes('limitations'), `cut=${cut} 泄漏了后续字段`);
    if (prefix) {
      assert.ok(
        '好，按你说的记：浙江考生，走第一段，2026年高考，六科成绩——语文112、数学125、外语118、物理85、化学86、生物84，总分610。'.startsWith(
          prefix
        ),
        `cut=${cut} 前缀不是全文的前缀：${prefix.slice(-20)}`
      );
    }
  }
});

test('转义处理：\\" \\\\ \\n 都按字面解码', () => {
  const raw = '{"message": "他说：\\"好的\\"，然后换了行\\n下一行，反斜杠\\\\也ok"}';
  assert.equal(extractStreamMessage(raw), '他说："好的"，然后换了行\n下一行，反斜杠\\也ok');
});

test('截断在转义中间：停在已解码前缀，不猜半个码点', () => {
  // 结尾是半个 \"（只有反斜杠）
  assert.equal(extractStreamMessage('{"message": "前半段\\'), '前半段');
  // 结尾是半个 \uXXXX
  assert.equal(extractStreamMessage('{"message": "前半段\\u4e'), '前半段');
  // 完整 \uXXXX 可解码
  assert.equal(extractStreamMessage('{"message": "\\u4f60\\u597d"}'), '你好');
});

test('message 字段还没出现 / 不是 JSON：返回空串（调用方保持闪烁卡，不铺原文）', () => {
  assert.equal(extractStreamMessage('{"responseType": "text", "mess'), '');
  assert.equal(extractStreamMessage('好的我来查一下'), '');
  assert.equal(extractStreamMessage(''), '');
  assert.equal(extractStreamMessage(undefined), '');
});

test('message 之后还有字段：到收尾引号即停，不带出后续内容', () => {
  const raw = '{"message": "答案", "next": "不应该出现"}';
  assert.equal(extractStreamMessage(raw), '答案');
});
