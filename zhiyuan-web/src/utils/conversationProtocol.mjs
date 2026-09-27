/**
 * 出站帧构造：把"用户做了什么"翻译成服务端认得的形状。
 *
 * 放在纯函数里而不是组件里，是因为这些形状**有对错**（服务端会拒收），
 * 而埋在 1771 行的组件里就只能靠人眼复核。
 *
 * 两条来自服务端合同的约束：
 * - 控制消息 `content` 必须为空串；只有 `turnSteer` 例外，它的转述文本
 *   没有别的字段可放（见 A2 的 WSMessage 校验）。
 * - `clarificationAnswer` 走**独立字段**，不能复用 `conversationAction`：
 *   后者的语义是"确认/取消一个提案"，混用会让两种完全不同的确认无法区分。
 */

export const PROTOCOL_VERSION = 1;

const requireText = (value, field) => {
  const text = String(value ?? '').trim();
  if (!text) throw new Error(`missing_${field}`);
  return text;
};

export const buildClarificationAnswerFrame = ({
  sessionId,
  turnId,
  requestId,
  answer,
  clientRequestId,
}) => ({
  protocolVersion: PROTOCOL_VERSION,
  type: 'clarificationAnswer',
  sessionId: requireText(sessionId, 'sessionId'),
  turnId: String(turnId ?? ''),
  clientRequestId: requireText(clientRequestId, 'clientRequestId'),
  // 控制消息的空串约定：载荷全在 clarificationAnswer 里。
  content: '',
  clarificationAnswer: {
    requestId: requireText(requestId, 'requestId'),
    ...answer,
  },
});

export const buildTurnInterruptFrame = ({ sessionId, turnId, clientRequestId }) => ({
  protocolVersion: PROTOCOL_VERSION,
  type: 'turnInterrupt',
  sessionId: requireText(sessionId, 'sessionId'),
  turnId: requireText(turnId, 'turnId'),
  clientRequestId: requireText(clientRequestId, 'clientRequestId'),
  content: '',
});

export const buildTurnSteerFrame = ({ sessionId, turnId, text, clientRequestId }) => ({
  protocolVersion: PROTOCOL_VERSION,
  type: 'turnSteer',
  sessionId: requireText(sessionId, 'sessionId'),
  turnId: requireText(turnId, 'turnId'),
  clientRequestId: requireText(clientRequestId, 'clientRequestId'),
  // turnSteer 是唯一必须带内容的控制消息：空的转述等于什么都没说，
  // 服务端会明确拒收（turn_steer_requires_content）。
  content: requireText(text, 'text'),
});

/** 稳定的重发 id：同一次作答重试必须沿用同一个 id，换新的等于答两次。 */
/**
 * **待采纳内容的采纳/放弃** ✓（老的消息卡与新的提案卡共用这一帧 ✓）。
 *
 * 两个细节必须照做 ✓（判据在服务端的 schema：`app/schemas/ws.py` 的 `WSMessage` ✓）：
 * ① `content` **必须是空串** ✗✓——schema 里它是 `content: str` ✓，塞对象会被拒 ✓；
 *    而"被拒"的表现是服务端回一条 `消息格式错误` ✓、**且不记日志** ✗✓
 *    （实测：点了"放弃"什么都没发生 ✓，agent 日志里只有握手 ✓——埋在组件里只能靠人眼复核 ✓，
 *     这正是本模块开头那句"出站帧抽成纯函数"要防的事 ✓）。
 * ② `type` 取 `pendingConfirmation` ✓（服务端 Literal 里有它 ✓；默认的 `chat` 语义不对 ✗）。
 */
export const buildPendingConfirmationFrame = ({
  sessionId,
  userId,
  action,
  proposalRef,
  sourceVersion,
  clientRequestId,
}) => ({
  type: 'pendingConfirmation',
  sessionId,
  userId,
  content: '',
  inputType: 'pendingConfirmation',
  conversationAction: {
    actionType: action === 'confirm' ? 'confirm_proposal' : 'cancel_proposal',
    proposalRef,
    expectedSourceVersion: sourceVersion,
    intent: 'explicit',
  },
  ...(clientRequestId ? { clientRequestId } : {}),
});

export const stableClientRequestId = (kind, key) => `${kind}-${key}`;
