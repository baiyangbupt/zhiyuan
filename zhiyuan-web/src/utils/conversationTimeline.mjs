/**
 * 会话时间线拼装：把**历史消息**与**事件流回合块**排成一条顺序正确的列表。
 *
 * 背景（2026-10-07 用户实测："自己发的消息被顶到上面了" ✗）：
 * 历史消息走 REST（按 id 升序），回合块走事件流（V1 转向量）——两块**各画各的**、
 * 回合块**永远追加在列表末尾** ✓✗。于是同一页面里每多发一轮，用户的新问题就往上挤一层 ✓、
 * 已答的回合块全堆在底部 ✗，问答配对彻底错位（实测：三问三答 → 三个问题在上、三个答案在下 ✓）。
 *
 * 修法：**把"已落定、且答案已经在历史里"的回合块锚到它那条历史记录的位置上** ✓✓——
 *   · 位置：答案记录在那里，回合块就画在那里（历史里的那条记录不再单独画）✓；
 *   · 去重：一个回合最多认领**一条**同文记录 ✓（同问同答的多轮各自认领、互不吞并 ✓）；
 *   · 不丢内容：认领不到（在飞回合、或答案还没落进历史）的回合块照旧排在**末尾** ✓
 *     ——那正是"最新一轮"该在的位置 ✓。
 *
 * 与旧口径（`v1AnsweredTexts` 按文本整体过滤历史）的差别 ✓：旧口径下，
 *   两次相同的答案只要有一个回合在手上，历史里两条记录会**一起被滤掉** ✗（少画一条）；
 *   锚定是**一对一**的 ✓，认领几条画几条，其余照常画 ✓。
 *
 * 纯函数：无 React、无副作用，可被 node:test 直接测。
 */

/** 同文归一：与历史/答案两侧共用的比较口径（空白折叠 + 去首尾）。 */
export const normalizeTimelineText = value => String(value === undefined || value === null ? '' : value).replace(/\s+/g, ' ').trim();

/** 回合的"可锚定文案"：终态答案或错误文案（未终态/没文案 → 空串，不参与锚定）。 */
export const turnAnchorText = turn => {
  if (!turn || !turn.terminal) return '';
  const raw = (turn.answer && turn.answer.message) || (turn.error && turn.error.message) || '';
  return normalizeTimelineText(raw);
};

const turnStart = turn => {
  const value = Number(turn && turn.startedAt);
  return Number.isFinite(value) ? value : 0;
};

/**
 * @param {{messages?: any[], turns?: any[]}} input
 *   messages: 已完成展示过滤的历史消息（升序 = 显示顺序）
 *   turns:    事件流折叠出的回合（任意顺序；本轮不渲染的回合由调用方自己 gate）
 * @returns {Array<{kind:'message', message:any} | {kind:'turn', turn:any}>}
 *   按显示顺序排列的渲染单元；`turn` 单元表示"这条历史记录的位置由回合块占位"。
 */
export function buildConversationTimeline(input) {
  const messages = (input && Array.isArray(input.messages) ? input.messages : []).filter(Boolean);
  const turns = (input && Array.isArray(input.turns) ? input.turns : []).filter(turn => turn && turn.id);

  // 回合按 startedAt 升序（缺失的排前，稳定按传入序）
  const orderedTurns = turns
    .map((turn, index) => ({ turn, index }))
    .sort((a, b) => turnStart(a.turn) - turnStart(b.turn) || a.index - b.index)
    .map(item => item.turn);

  // 历史里可被认领的记录：助手 TEXT 消息，按归一文本索引（同文多条按升序排队）
  const recordsByText = new Map();
  const indexById = new Map();
  messages.forEach((message, index) => {
    indexById.set(String(message.id), index);
    if (message.messageFrom !== '0' || message.contentType !== 'TEXT') return;
    const key = normalizeTimelineText(message.content);
    if (!key) return;
    const list = recordsByText.get(key) || [];
    list.push(index);
    recordsByText.set(key, list);
  });

  const claimedByIndex = new Map();
  const unanchored = [];
  // **从最新回合往回认领** ✓：手里只有最新一轮时，它认领的是**最新**那条同文记录 ✓
  //（若从旧往新认领会把最新回合锚到旧位置上 ✗）。
  for (let cursor = orderedTurns.length - 1; cursor >= 0; cursor -= 1) {
    const turn = orderedTurns[cursor];
    const key = turnAnchorText(turn);
    const candidates = key ? recordsByText.get(key) : undefined;
    if (candidates && candidates.length > 0) {
      const messageIndex = candidates.pop();
      claimedByIndex.set(messageIndex, turn);
    } else {
      unanchored.push(turn);
    }
  }

  const items = [];
  messages.forEach((message, index) => {
    const turn = claimedByIndex.get(index);
    if (turn) {
      items.push({ kind: 'turn', turn });
      return;
    }
    items.push({ kind: 'message', message });
  });
  unanchored
    .slice()
    .sort((a, b) => turnStart(a) - turnStart(b))
    .forEach(turn => items.push({ kind: 'turn', turn }));
  return items;
}
