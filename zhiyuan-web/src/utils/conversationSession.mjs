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
      // `order` 记**首次出现**的事件序号：展示时靠它判断"连续"，从而把
      // 同工具同标签的一串调用（如 15 次选科核验）折叠成一条 ×N。
      const itemId = payload.itemId || `step-${event.sequence}`;
      const priorStep = prior.steps[itemId];
      const steps = {
        ...prior.steps,
        [itemId]: {
          itemId,
          tool: payload.tool || 'domain',
          status: payload.status || 'started',
          label: payload.label || '',
          order: priorStep ? priorStep.order : event.sequence,
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

    case 'interpretation.preview':
      // 只覆盖最近一次解读：同一回合多次调用时以最后一次为准（不堆多张卡）。
      return mergeTurn(state, turnId, { interpretation: { ...payload } });

    case 'conversationAction.result': {
      const next = { ...payload };
      const previous = prior.actionResult;
      if (previous && TERMINAL_ACTION_STATUSES.has(previous.actionStatus)
          && !TERMINAL_ACTION_STATUSES.has(next.actionStatus)) {
        // applied 之后再来的 applying 是迟到的旧事件，不能把它刷回去——
        // 用户会先看到"已生效"再看到"确认中"，然后不确定到底生效没有。
        return state;
      }
      // J3：同一 operationId 的重复回执只保留第一张卡（重复确认/重放不刷第二遍）。
      if (previous?.receipt?.operationId && next.receipt?.operationId
          && String(previous.receipt.operationId) === String(next.receipt.operationId)
          && TERMINAL_ACTION_STATUSES.has(previous.actionStatus)) {
        return state;
      }
      return mergeTurn(state, turnId, { actionResult: next });
    }

    case 'assistant.delta': {
      // 增量是**可丢弃的提示**（首字延迟感知）：只往回合里攒，不单独建渲染面
      // （没有内容的空回合会被页面 gate 挡住，这条守卫在页面那侧）。
      // **终态是权威**：已终态的回合不再接受增量——迟到的增量不许把已经落定的
      // 答案刷回"流式中的样子"（终态事件照旧只落一次）。
      if (prior.terminal) return state;
      const chunk = typeof payload.chunk === 'string' ? payload.chunk : '';
      if (!chunk) return state;
      return mergeTurn(state, turnId, { answerStream: (prior.answerStream || '') + chunk });
    }

    case 'assistant.completed':
      // 权威答案到达：**整段替换**流式文本（`answerStream` 作废）——
      // 流文本与终态文本不叠加，页面因此不会画出两份答案。
      return mergeTurn(state, turnId, {
        answer: { ...payload },
        answerStream: '',
        terminal: true,
      });

    case 'turn.completed':
      // 运行结束 ≠ 用户诉求完成：executionStatus 与 toolStatus 是两个字段，
      // 都原样保留，不在这里互相推导。
      // 流式文本同样作废：这一轮结束了，没等到 `assistant.completed` 的
      // （失败/中断）也不该把半截流文本留在回合里。
      return mergeTurn(state, turnId, {
        ...payload,
        executionStatus: payload.executionStatus || prior.executionStatus || 'completed',
        answerStream: '',
        terminal: true,
      });

    case 'recoverable.error': {
      // **空文案不许覆盖已有文案** ✓✓：同一条失败会走两条路到前端 ✓（V1 事件先到、
      // 带服务端的具体文案 ✓；老信封兜底帧后到 ✓——失败结果里没有 `reply` 时它的
      // `message` 是空串 ✗，见 `server.py` 的 `_native_reply_frame` ✓）。直接整体覆盖
      // 会把刚带到的文案擦掉 ✗，用户只剩渲染层那句通用兜底 ✓（`MessageList` 的注释
      // 记着实测 ✓）。拦的**只有空值** ✓：真有新文案时照旧"后到者胜" ✓。
      const next = { ...payload };
      if (!next.message && prior.error?.message) {
        next.message = prior.error.message;
      }
      return mergeTurn(state, turnId, { error: next });
    }

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

/**
 * 工具进度**展示序列**：同一工具、同一标签的**连续**步骤合并成一条，带 `count`。
 *
 * 2026-10-17 真事故：一个续接回合做了 15 次 `admission.check_eligibility`，
 * 页面上就是 15 行"核对选科要求"（用户看到的"约 20 次调用"）。这些调用本身
 * 是合法的（不同专业），但**逐行铺开**只是噪音——合并成一条 `×15` 既保留
 * "做了多少次"的事实，又不占满屏幕。
 *
 * 只合并**连续**的：中间夹了别的工具就断开，顺序信息来自 reducer 记的 `order`
 * （`steps` 是对象，数字型 itemId 的遍历顺序不可靠）。
 * 同一 itemId 的 start/completed 仍由 reducer 归并，不会在这里重复计数。
 */
export const orderedSteps = turn => {
  const steps = Object.values((turn && turn.steps) || {})
    .filter(step => step && typeof step === 'object')
    .sort((a, b) => (a.order || 0) - (b.order || 0));
  const merged = [];
  for (const step of steps) {
    const tool = step.tool || 'domain';
    const label = step.label || '';
    const last = merged[merged.length - 1];
    if (last && last.tool === tool && last.label === label) {
      last.count += 1;
      last.status = step.status;
      continue;
    }
    merged.push({ ...step, tool, label, count: 1 });
  }
  return merged;
};

export const pendingClarifications = turn =>
  Object.values((turn && turn.clarifications) || {}).filter(item => item.status === 'pending');
