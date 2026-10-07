/**
 * 从**未闭合**的结构化输出 JSON 中，增量抽取给用户看的**人话文本**（`message` 字段）。
 *
 * 背景（2026-10-07 用户实测）：`assistant.delta` 流的是原始 TurnOutput JSON 碎片
 * （`{"responseType": "text", "message": "…"`），直接铺给用户看是观感事故 ✗——
 * 满屏引号括号和字段名。这里只做一件事：把 `message` 字符串的**可读前缀**取出来。
 *
 * 三条设计口径：
 *   1. **只读不猜**：抽不到（message 字段还没出现 / 不是 JSON）就返回空串 ✓，
 *      调用方保持"正在分析"的闪烁卡，**绝不**把原文铺出去 ✗；
 *   2. **增量友好**：字符串未闭合是常态 ✓——按已到达的部分解码，截断在转义中间
 *      也安全停在已解码前缀 ✓；
 *   3. **不改协议**：这只是渲染层过滤 ✓；终态 `assistant.completed` 到达后仍整段替换
 *      （终态权威那条不变量不动 ✓）。
 *
 * @param {string} raw 累积的原始流式文本（可能未闭合、可能含任意截断）
 * @returns {string} 可直接展示的人话前缀；无内容时为空串
 */
export function extractStreamMessage(raw) {
  if (typeof raw !== 'string' || raw.length === 0) {
    return '';
  }
  // 定位 `"message"` 字段的字符串起点（键名允许空白，值必须以引号开始）
  const match = /"message"\s*:\s*"/.exec(raw);
  if (!match) {
    return '';
  }
  let index = match.index + match[0].length;
  let out = '';
  while (index < raw.length) {
    const ch = raw[index];
    if (ch === '\\') {
      const esc = raw[index + 1];
      if (esc === undefined) {
        // 截断在转义开头（最后一个字符是反斜杠）：停在已解码前缀
        break;
      }
      if (esc === 'n') {
        out += '\n';
      } else if (esc === 't') {
        out += '\t';
      } else if (esc === 'r') {
        out += '\r';
      } else if (esc === 'u') {
        const hex = raw.slice(index + 2, index + 6);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
          // 截断的 \uXXXX：不要猜半个码点
          break;
        }
        out += String.fromCharCode(parseInt(hex, 16));
        index += 6;
        continue;
      } else {
        // \" \\ \/ 以及未知转义：按转义后的字面字符展示
        out += esc;
      }
      index += 2;
      continue;
    }
    if (ch === '"') {
      // 未转义引号 = 字符串收尾，message 已完整
      break;
    }
    out += ch;
    index += 1;
  }
  return out;
}

export default extractStreamMessage;
