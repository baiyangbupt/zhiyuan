/**
 * 会话事件 reducer：把服务端事件流折叠成页面状态。
 *
 * 纯函数、无副作用、无 React —— 这样它既能被 node:test 直接测，也能被组件复用。
 * 它唯一的输入是事件，唯一的输出是新状态；任何"顺手做点别的"都会让测试
 * 与线上行为分叉。
 *
 * 三条不变量：
 * 1. **同一会话**：别的会话的事件一律不理，不能污染当前页。
 * 2. **代际 + 序号**：编号稠密单调，缺口就是丢事件的证据，只能 resync。
 * 3. **终态只落一次**：重复的终态事件不产生第二次完成。
 */

/**
 * 老信封转换产物用的**本地占位代际** ✓——由 `conversationEvents.mjs` 生成 ✓，
 * 字面量必须与那边一致 ✓（它不是一条时间线 ✓，只是"这条帧没有真编号"的标记 ✓）。
 */
export const LOCAL_EPOCH = 'local';

export const EMPTY_STATE = Object.freeze({
  sessionId: '',
  streamEpoch: null,
  lastSequence: 0,
  turns: {},
  needsResync: false,
});

/** 已决状态：一旦到 applied 就不再回退。 */
const TERMINAL_ACTION_STATUSES = new Set(['applied', 'cancelled', 'expired']);

export const createConversationState = sessionId => ({
  ...EMPTY_STATE,
  sessionId: String(sessionId || ''),
  turns: {},
});

const mergeTurn = (state, turnId, patch) => {
  const prior = state.turns[turnId] || { id: turnId, steps: {}, clarifications: {} };
  return { ...state, turns: { ...state.turns, [turnId]: { ...prior, ...patch } } };
};

const applyToTurn = (state, event) => {
  const payload = event.payload || {};
  const turnId = event.turnId;
  const prior = state.turns[turnId] || { id: turnId, steps: {}, clarifications: {} };

  switch (event.type) {
    case 'turn.started':
      return mergeTurn(state, turnId, { startedAt: event.sequence });

    case 'turn.phase':
      return mergeTurn(state, turnId, { phase: { ...payload } });

    case 'tool.progress': {
      // 工具进度按 itemId 归并：同一个 item 的 start/completed 是两条事件，
      // 覆盖成一条步骤，而不是在数组里堆两条。
      const itemId = payload.itemId || `step-${event.sequence}`;
      const steps = {
        ...prior.steps,
        [itemId]: {
          itemId,
          tool: payload.tool || 'domain',
          status: payload.status || 'started',
          label: payload.label || '',
        },
      };
      return mergeTurn(state, turnId, { steps });
    }

    case 'understanding.preview':
      return mergeTurn(state, turnId, { understanding: { ...payload } });

    case 'clarification.requested':
      return mergeTurn(state, turnId, {
        clarifications: {
          ...prior.clarifications,
          [payload.requestId]: { ...payload, status: 'pending' },
        },
      });

    case 'clarification.resolved': {
      const existing = prior.clarifications[payload.requestId];
      if (!existing) return state;
      return mergeTurn(state, turnId, {
        clarifications: {
          ...prior.clarifications,
          [payload.requestId]: { ...existing, status: payload.status || 'resolved' },
        },
      });
    }

    case 'proposal.preview':
      return mergeTurn(state, turnId, { proposal: { ...payload } });

    case 'conversationAction.result': {
      const next = { ...payload };
      const previous = prior.actionResult;
      if (previous && TERMINAL_ACTION_STATUSES.has(previous.actionStatus)
          && !TERMINAL_ACTION_STATUSES.has(next.actionStatus)) {
        // applied 之后再来的 applying 是迟到的旧事件，不能把它刷回去——
        // 用户会先看到"已生效"再看到"确认中"，然后不确定到底生效没有。
        return state;
      }
      return mergeTurn(state, turnId, { actionResult: next });
    }

    case 'assistant.completed':
      return mergeTurn(state, turnId, { answer: { ...payload }, terminal: true });

    case 'turn.completed':
      // 运行结束 ≠ 用户诉求完成：executionStatus 与 toolStatus 是两个字段，
      // 都原样保留，不在这里互相推导。
      return mergeTurn(state, turnId, {
        ...payload,
        executionStatus: payload.executionStatus || prior.executionStatus || 'completed',
        terminal: true,
      });

    case 'recoverable.error':
      return mergeTurn(state, turnId, { error: { ...payload } });

    default:
      return state;
  }
};

export function reduceConversation(state, event) {
  if (!state || !event || typeof event !== 'object') return state;
  if (String(event.sessionId || '') !== String(state.sessionId || '')) {
    // 别的会话的事件：忽略。跨会话污染会让用户在新会话里看到旧答案。
    return state;
  }
  if (event.type === 'session.resync') {
    // resync 是控制快照：它**重置**基线，而不是接在基线后面。
    const baseline = (event.payload && event.payload.baseline) || {};
    return {
      ...EMPTY_STATE,
      ...baseline,
      sessionId: state.sessionId,
      streamEpoch: event.streamEpoch || null,
      lastSequence: baseline.lastSequence || 0,
      turns: baseline.turns || {},
      needsResync: false,
    };
  }
  if (state.streamEpoch === null) {
    // 首帧：还没有代际可比较，接受它作为基线。
    // 反过来要求第一帧序号必须是 1，会让"服务端从第 7 条开始发"变成永久 resync。
    const adopted = applyToTurn(
      { ...state, streamEpoch: event.streamEpoch, lastSequence: 0 },
      event,
    );
    // 采纳代际的同时也要采纳序号：不推进的话下一条正常事件会被当成"缺口"，
    // 于是首帧之后立刻永久 resync。
    return { ...adopted, lastSequence: event.sequence };
  }
  if (state.streamEpoch === LOCAL_EPOCH && event.streamEpoch !== LOCAL_EPOCH) {
    // **手里那个代际只是本地占位时，真代际一到就直接采纳** ✓✓。
    //
    // 老信封转换产物用的是常量 `local`（`conversationEvents.mjs` ✓），它**不是**一条
    // 时间线 ✓。把它当真代际去比对，就会变成"每次混流都换代"✗——而失败回合**总会**
    // 带一条老信封兜底帧 ✓（网关有意两条都发 ✓：老 UI 靠 reply ✓、新 UI 靠 V1 ✓），
    // 于是每失败一次就清一次界面 ✓✗，用户看到的是"回合块没了" ✓。
    // A6 报告早就点过这个风险（"老信封路径需要与真代际分开命名空间 ✗，
    // 否则一旦混流就会不断触发换代 resync" ✓）——这里就是那一步 ✓。
    // 与首帧同一种处置 ✓：采纳真代际、不判换代 ✓（序号也一并采纳 ✓）。
    const adopted = applyToTurn(
      { ...state, streamEpoch: event.streamEpoch, lastSequence: 0 },
      event,
    );
    return { ...adopted, lastSequence: event.sequence };
  }
  if (event.streamEpoch === LOCAL_EPOCH && state.streamEpoch !== LOCAL_EPOCH) {
    // **本地占位不带时间线信息** ✓✓：手里已经是**真代际**时，这条老信封帧既不能顶替它 ✓、
    // 也不能触发 resync ✗——它只是"这帧没有真编号"的标记 ✓。
    // 实测（探针原文 ✓）：失败回合的老信封兜底帧**最后到** ✓ →
    // `applied=true, needsResync=true` ✗ → 刚刚建好的回合块被判成缺口清掉 ✓，
    // 用户看到的是"消息发出去了、回合没了" ✓。
    // 所以：**照常折叠进回合**（内容该显示就显示 ✓），但代际与序号**一动不动** ✗、
    // 缺口判断也**不参与** ✓。
    return applyToTurn(state, event);
  }
  if (event.streamEpoch !== state.streamEpoch) {
    return { ...state, needsResync: true };
  }
  if (typeof event.sequence !== 'number' || event.sequence <= state.lastSequence) {
    return state;
  }
  if (event.sequence !== state.lastSequence + 1) {
    return { ...state, needsResync: true };
  }

  const next = applyToTurn(state, event);
  return { ...next, lastSequence: event.sequence };
}

/**
 * 理解卡只在**真有**结构化理解时出现。
 *
 * 设计里明写"没有模型结构化理解时不预制'我理解你想……'的卡"——那种卡是
 * 揣测用户意图，而揣测错的代价是用户以为系统听懂了。
 */
export const hasStructuredUnderstanding = payload => {
  if (!payload || typeof payload !== 'object') return false;
  const summary = typeof payload.summary === 'string' ? payload.summary.trim() : '';
  const entities = Array.isArray(payload.entities) ? payload.entities : [];
  const constraints = Array.isArray(payload.constraints) ? payload.constraints : [];
  return Boolean(summary) || entities.length > 0 || constraints.length > 0;
};

export const orderedTurns = state =>
  Object.values(state.turns).sort((a, b) => (a.startedAt || 0) - (b.startedAt || 0));

export const pendingClarifications = turn =>
  Object.values((turn && turn.clarifications) || {}).filter(item => item.status === 'pending');
