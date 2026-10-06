import React, { useEffect, useState, useRef, forwardRef, useImperativeHandle, useCallback } from 'react';
import { message, Spin, Empty, Button, Input, Row, Col, Card, Checkbox, Modal } from 'antd';
import {
  CheckCircleOutlined,
  DislikeOutlined,
  LikeOutlined,
  VerticalAlignBottomOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import {
  IUserInfoParams,
  IWsMessage,
  IMessage,
} from '@/interface/api/sessionDetail';
import { PlanningWorkspaceIntent, PlanningWorkspaceRefreshTarget } from '@/interface/api/volunteer';
import {
  getEntityPropertyAnalyzeApi,
  getMessageListApi,
  getFeedbackApi,
} from '@/service/apis/sessionDetail';
import { socketBase } from '@/utils/conversationSocket.mjs';
import { cursorFromState } from '@/utils/conversationCursor.mjs';
import style from './style.module.scss';
import { TextSegment } from '@/interface/api/sessionDetail';
import useAuthParams from '@/hooks/useAuthParams';
import { useWebSocket } from '@/hooks/useWebSocket';
import {
  createConversationState,
  pendingClarifications,
  reduceConversation,
} from '@/utils/conversationSession.mjs';
import { isConversationV1Event, toConversationEvent } from '@/utils/conversationEvents.mjs';
import { fetchWsTicketApi } from '@/service/apis/conversationAccess';
import {
  buildClarificationAnswerFrame,
  buildPendingConfirmationFrame,
  buildTurnInterruptFrame,
  buildTurnSteerFrame,
  stableClientRequestId,
} from '@/utils/conversationProtocol.mjs';
import ClarificationCard from '@/pageComponents/sessionDetailV2/ConversationEvents/ClarificationCard';
import ProposalCard from '@/pageComponents/sessionDetailV2/ConversationEvents/ProposalCard';
import UnderstandingCard from '@/pageComponents/sessionDetailV2/ConversationEvents/UnderstandingCard';
import { WebSocketMessage } from '@/hooks/websocket';
import TypingAnimation from '@/components/generating/TypingAnimation';
import SendPng from '@/images/icons/send.png';
import { marked } from 'marked';
import { createFetchQueue } from './fetchQueue.mjs';
import { applyPendingActionResult, parseConversationActionResult } from '@/utils/conversationEvents.mjs';

marked.use({ gfm: true, breaks: true });

const renderMarkdown = (content: string) => marked.parse(content) as string;

const OPTIMISTIC_MESSAGE_ID_BASE = 1_000_000_000_000;

interface IOptimisticMessage extends IMessage {
  optimistic?: boolean;
  optimisticAfterId?: number;
}

interface ITransientAgentMessage extends IMessage {
  transient?: boolean;
}

const isOptimisticUserMessage = (record: IMessage): record is IOptimisticMessage =>
  record.messageFrom === '1' &&
  record.contentType === 'TEXT' &&
  (record.id >= OPTIMISTIC_MESSAGE_ID_BASE || Boolean((record as IOptimisticMessage).optimistic));

const hasMatchingRealUserMessage = (optimistic: IOptimisticMessage, records: IMessage[]) => {
  const afterId = optimistic.optimisticAfterId ?? 0;
  return records.some(
    record =>
      record.id < OPTIMISTIC_MESSAGE_ID_BASE &&
      record.id > afterId &&
      record.messageFrom === '1' &&
      record.contentType === 'TEXT' &&
      (record.content || '') === (optimistic.content || '')
  );
};

const isTransientAgentMessage = (record: IMessage): record is ITransientAgentMessage =>
  record.messageFrom === '0' && Boolean((record as ITransientAgentMessage).transient);

const hasMatchingRealAgentMessage = (transient: ITransientAgentMessage, records: IMessage[]) =>
  records.some(
    record =>
      record.id < OPTIMISTIC_MESSAGE_ID_BASE &&
      record.messageFrom === '0' &&
      record.contentType === transient.contentType &&
      (record.content || '') === (transient.content || '')
  );

interface IQuickReplyAction {
  label: string;
  icon: React.ReactNode;
  onClick?: () => void;
  messageText?: string;
}

interface IMessageListProps {
  routerParams: IUserInfoParams;
  scrollEleIndex?: number;
  setEntityCardList?: (value: any) => void;
  setScrollEleIndex: (index: number) => void;
  setFetchFlag: React.Dispatch<React.SetStateAction<number>>;
  isTencentMeeting?: boolean;
  doChatRights?: {
    canOperate: boolean;
    reason?: string;
  };
  quickReplyActions?: IQuickReplyAction[];
  alwaysShowQuickReplyActions?: boolean;
  onWorkspaceIntent?: (intent: Omit<PlanningWorkspaceIntent, 'nonce'>) => void;
  /**
   * **会话里最后一条提案的落定状态**（来自会话详情 ✓）：冷加载时补一张卡用 ✓✗。
   *
   * 为什么需要 ✗✓：卡片状态今天**只活在事件流里** ✓（`proposal.preview` / `conversationAction.result` ✓），
   * 而刷新/重连之后客户端**没有游标** ✓（`conversationCursor.mjs` 的口径：游标不落盘 ✓），
   * 服务端那条路只补"在飞回合" ✗，已结束回合的卡片事件一条都不补 ✓ → 卡**重建不出来** ✗
   * （F13 用例的第③条 ✓）。所以服务端把"最后一条提案 + 动作状态"放进会话详情 ✓，
   * 这里在**没有回合卡**时补一张**只读**的卡 ✓（状态照 `ProposalCard` 的映射 ✓，`applied` → 已生效 ✓）。
   */
  lastProposal?: {
    proposalRef?: string;
    proposalId?: string;
    actionStatus?: string;
  } | null;
}
export interface IMessageParams {
  onNewMessage: (payload: IWsMessage) => void;
  fetchMessageList: (tempPage?: number) => void;
  setPage: (page: number) => void;
  setAutoScroll: (flag: boolean) => void;
}

interface IThinkingMessage {
  type?: string;
  content?: string;
  end?: boolean;
}

interface IIntentCardItem {
  content?: string;
  value?: Record<string, unknown>;
  selected?: boolean;
}

interface IIntentAnalysisContent {
  stage?: string;
  summaryTitle?: string;
  currentPlanFit?: string[];
  currentPlanConflict?: string[];
  candidateOpportunity?: string[];
  nextActionHints?: string[];
}

interface IInterestAction {
  label: string;
  message?: string;
  actionType?: string;
}

interface IIntentCardContent {
  type?: string;
  title?: string;
  content?: string;
  items?: IIntentCardItem[];
  existing_items?: Array<{ content?: string }>;
  impact?: string;
  impactTitle?: string;
  analysis?: IIntentAnalysisContent;
  actions?: IInterestAction[];
  intentMode?: 'preference' | 'constraint';
  clickable?: boolean;
  clicked?: boolean;
  actionText?: string;
  targetView?: PlanningWorkspaceIntent['targetView'] | PlanningWorkspaceRefreshTarget;
  refreshTargets?: PlanningWorkspaceRefreshTarget[];
  volunteerIds?: string[];
  refresh?: boolean;
  preserveView?: boolean;
  silent?: boolean;
  candidateFilters?: PlanningWorkspaceIntent['candidateFilters'];
  kind?: 'intent_change' | 'plan_mutation';
  actionFamily?: string;
  summary?: string;
  pendingId?: string;
  proposalRef?: string;
  sourceVersion?: number;
  status?: 'active' | 'applying' | 'applied' | 'cancelled' | 'replaced' | 'expired' | 'stale_state' | 'failed';
  confirmText?: string;
  cancelText?: string;
}

const isIntentConfirmCard = (contentObj?: IIntentCardContent | null) =>
  contentObj?.type === 'planEditSelectPopup' ||
  contentObj?.type === 'intentDetectSelectPopup' ||
  contentObj?.type === 'intentConfirmPopup';

const isInterestAnalysisOnlyCard = (contentObj?: IIntentCardContent | null) =>
  contentObj?.type === 'interestAnalysisPopup';

const isPendingConfirmationCard = (contentObj?: IIntentCardContent | null) =>
  contentObj?.type === 'pendingConfirmationCard';

const isWorkspaceActionCard = (contentObj?: IIntentCardContent | null) =>
  contentObj?.type === 'planningWorkspaceAction';

const isIntentAnalysisCard = (contentObj?: IIntentCardContent | null) =>
  isIntentConfirmCard(contentObj) || isInterestAnalysisOnlyCard(contentObj);

const supportedWorkspaceTargetViews = new Set(['candidate', 'ordered']);
const supportedWorkspaceRefreshTargets = new Set(['candidate', 'ordered', 'review', 'draft', 'workingPlan']);

const normalizeWorkspaceTargetView = (
  targetView: unknown
): PlanningWorkspaceIntent['targetView'] | null => {
  if (typeof targetView !== 'string' || !supportedWorkspaceTargetViews.has(targetView)) {
    return null;
  }
  return targetView as PlanningWorkspaceIntent['targetView'];
};

const normalizeWorkspaceRefreshTargets = (contentObj: Record<string, any>): PlanningWorkspaceRefreshTarget[] => {
  const rawTargets = Array.isArray(contentObj.refreshTargets)
    ? contentObj.refreshTargets
    : Array.isArray(contentObj.workspaceRefreshTargets)
      ? contentObj.workspaceRefreshTargets
      : [];
  const targets = rawTargets
    .filter((target): target is string => typeof target === 'string')
    .filter(target => supportedWorkspaceRefreshTargets.has(target)) as PlanningWorkspaceRefreshTarget[];
  if (typeof contentObj.targetView === 'string' && supportedWorkspaceRefreshTargets.has(contentObj.targetView)) {
    targets.push(contentObj.targetView as PlanningWorkspaceRefreshTarget);
  }
  return Array.from(new Set(targets));
};

const isStructuredIntentSelectEcho = (record: IMessage) => {
  if (record.messageFrom !== '1' || record.contentType !== 'TEXT') {
    return false;
  }
  try {
    const parsed = JSON.parse(record.content);
    return (
      parsed &&
      typeof parsed === 'object' &&
      parsed.action === '采纳' &&
      typeof parsed.message_id !== 'undefined' &&
      Array.isArray(parsed.selected)
    );
  } catch (error) {
    return false;
  }
};

const isLegacyAutoPlanPrompt = (record: IMessage, index: number, records: IMessage[]) => {
  if (
    record.messageFrom !== '1' ||
    record.contentType !== 'TEXT' ||
    (record.content || '').trim() !== '方案有了么' ||
    index > 2
  ) {
    return false;
  }
  const hasPreviousUserMessage = records
    .slice(0, index)
    .some(item => item.messageFrom === '1' && !isStructuredIntentSelectEcho(item));
  const hasLaterAssistantReply = records.slice(index + 1).some(item => item.messageFrom === '0');
  return !hasPreviousUserMessage && !hasLaterAssistantReply;
};

const parseWorkspaceIntentPayload = (
  data: unknown
): Omit<PlanningWorkspaceIntent, 'nonce'> | null => {
  if (!data || typeof data !== 'object') {
    return null;
  }
  const payload = data as Record<string, any>;
  const contentObj =
    payload.type === 'planningWorkspaceAction' && payload.content && typeof payload.content === 'object'
      ? payload.content
      : payload;
  if (contentObj?.type !== 'planningWorkspaceAction') {
    return null;
  }
  const targetView = normalizeWorkspaceTargetView(contentObj.targetView);
  const refreshTargets = normalizeWorkspaceRefreshTargets(contentObj);
  if (!targetView && refreshTargets.length === 0) {
    return null;
  }
  return {
    targetTab: 'volunteer',
    targetView: targetView || undefined,
    refreshTargets,
    volunteerIds: Array.isArray(contentObj.volunteerIds) ? contentObj.volunteerIds : [],
    refresh: Boolean(contentObj.refresh),
    preserveView: Boolean(contentObj.preserveView),
    silent: Boolean(contentObj.silent),
    candidateFilters: contentObj.candidateFilters,
  };
};

const workspaceActionFallbackCopy = (contentObj: Record<string, any>) => {
  const targetView = contentObj?.targetView;
  if (targetView === 'candidate') {
    return {
      title: '查看候选库关联结果',
      content: '打开候选库，查看跟刚才偏好或排除要求相关的候选机会。',
      actionText: '打开候选库',
    };
  }
  if (targetView === 'ordered') {
    return {
      title: '查看调整后的排序方案',
      content: '打开排序方案，查看本次调整后的志愿列表和位置变化。',
      actionText: '打开排序方案',
    };
  }
  return {
    title: '查看工作台更新',
    content: '工作台已有更新，可以打开对应区域查看最新结果。',
    actionText: '查看更新',
  };
};

/**
 * **动作回包按 `proposalRef` 找** ✓✓——不能只看**提案那个回合** ✗：
 * 网关为"采纳/放弃"这动作**另起一轮** ✓（`conversationAction.result` 挂在新回合上 ✓），
 * 而卡片画在提案那一轮里 ✓ → 只看本回合就永远是"待确认" ✓
 *（实测：事件流里明明有 `actionStatus: "cancelled"` ✓，卡上还是"待确认" ✓）。
 * 取**最后一条**匹配的 ✓（同一张卡可能先 applying 后 applied ✓）。
 */
function findActionResultFor(state: any, proposalRef?: string) {
  if (!proposalRef) return undefined;
  // **终态不许被迟到的失败盖掉** ✓✓（与 reducer 里"迟到的 applying 不能刷回终态"同一条精神 ✓）：
  // 实测（F08 双击 ✓）：第一次点"采纳"→ claim → execute **只跑了一次** ✓ → `applied` ✓；
  // 第二次点击的 claim 落在"已经执行完的 pending"上 ✗ → 回一条 `failed` ✗✓ ——
  // 取"最后一条"就会把它显示成"未生效" ✗✓，而用户那次确认其实**成功了** ✓。
  const terminal = new Set(['applied', 'cancelled', 'declined', 'expired']);
  let found: { actionStatus?: string; proposalRef?: string } | undefined;
  for (const candidate of Object.values(state?.turns || {}) as any[]) {
    const result = candidate?.actionResult;
    if (!result || String(result.proposalRef || '') !== String(proposalRef)) continue;
    const status = String(result.actionStatus || '');
    if (found && terminal.has(String(found.actionStatus || '')) && !terminal.has(status)) continue;
    found = result;
  }
  return found;
}

const MessageList = forwardRef<IMessageParams, IMessageListProps>((props, ref) => {
  const {
    routerParams,
    scrollEleIndex,
    setEntityCardList,
    quickReplyActions,
    alwaysShowQuickReplyActions,
    onWorkspaceIntent,
    lastProposal,
    setScrollEleIndex,
    setFetchFlag,
    doChatRights,
  } = props;
  const [messageList, setMessageList] = useState<IMessage[]>([]);
  const messageContainerRef = useRef<HTMLDivElement>(null); // 创建 ref
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isMore, setIsMore] = useState(false);
  const [wsMessageList, setWsMessageList] = useState<IMessage[]>([]);
  const [isReachBottom, setIsReachBottom] = useState(true);

  const [userInput, setUserInput] = useState<string>();

  // 关键词属性
  const itemRefs = useRef<any>([]);

  const { botId, tenantId } = useAuthParams();

  const prevMessageListRef = useRef<IMessage[]>([]);
  const pageRef = useRef(1);
  const fetchQueueRef = useRef<{ enqueue: (page?: number) => Promise<void> } | null>(null);
  const optimisticMessageSeqRef = useRef(0);
  const activeChatSessionIdRef = useRef(routerParams.chatSessionId);

  const [checkedMap, setCheckedMap] = useState<Record<number, boolean[]>>({});

  const updateMessageList = () => {
    if (wsMessageList.length) {
      console.log('更新会话列表', wsMessageList);
      setMessageList(prevList => [...prevList, ...wsMessageList]);
      setWsMessageList([]);
    }
  };
  // 滚动到容器底部（移动端需要延迟确保 DOM 布局完成）
  const scrollToBottom = () => {
    updateMessageList();
    // 使用 requestAnimationFrame + setTimeout 确保移动端 DOM 渲染和布局完成后再滚动
    requestAnimationFrame(() => {
      setTimeout(() => {
        if (messageContainerRef.current) {
          const el = messageContainerRef.current;
          el.scrollTop = el.scrollHeight;
          setIsReachBottom(true);
        }
      }, 100);
    });
  };
  const onMessageHandler = (payload: IWsMessage) => {
    // 已注释，保留函数定义以保持接口一致性
  };

  const onNewMessage = (payload: IWsMessage) => {
    console.log(payload, '---收到新消息');
    onMessageHandler(payload);
  };
  useImperativeHandle(ref, () => ({
    onNewMessage,
    fetchMessageList,
    setPage,
    setAutoScroll,
  }));

  useEffect(() => {
    const hasMore = page * 10 < total; // 假设每页加载20条数据
    setIsMore(hasMore);
  }, [total, page]);

  useEffect(() => {
    pageRef.current = page;
  }, [page]);

  const fetchMessageList = useCallback(
    async (tempPage?: number) => {
      if (!fetchQueueRef.current) {
        fetchQueueRef.current = createFetchQueue(async (queuedPage?: number) => {
          const requestChatSessionId = routerParams.chatSessionId;
          const currentPage = queuedPage ?? pageRef.current;

          setIsLoading(true);

          const container = messageContainerRef.current;
          // 记录当前滚动位置和高度
          const prevScrollHeight = container?.scrollHeight || 0;
          const prevScrollTop = container?.scrollTop || 0;
          try {
            const { data, code } = await getMessageListApi(routerParams.tenantId, {
              chatSessionId: +requestChatSessionId,
              orderBy: [
                // 排序规则
                { isAsc: false, orderBy: 'id' },
              ],
              page: currentPage,
              pageSize: 10,
            });
            if (activeChatSessionIdRef.current !== requestChatSessionId) {
              return;
            }
            if (code === 0 && data) {
              const reverseList = data.records
                .filter(record => !isStructuredIntentSelectEcho(record))
                .reverse();
              const dealReverseList = reverseList.map(record => ({
                ...record,
                contentSegments: record.contentSegments,
              }));
              setMessageList(prevList => {
                const prevWithoutMatchedOptimistic = prevList.filter(
                  record =>
                    (
                      !isOptimisticUserMessage(record) ||
                      !hasMatchingRealUserMessage(record, dealReverseList)
                    ) &&
                    (
                      !isTransientAgentMessage(record) ||
                      !hasMatchingRealAgentMessage(record, dealReverseList)
                    )
                );
                const merged = [...dealReverseList, ...prevWithoutMatchedOptimistic]
                  .reduce((acc: IMessage[], current: IMessage) => {
                    if (!acc.some(item => item.id === current.id)) {
                      acc.push(current);
                    }
                    return acc;
                  }, [] as IMessage[])
                  .sort((a: IMessage, b: IMessage) => a.id - b.id);
                if (prevMessageListRef.current.length === 0) {
                  prevMessageListRef.current = merged;
                }
                return merged;
              });
              setTotal(data.total);
              if (currentPage === 1 && autoScroll) {
                scrollToBottom();
              } else {
                // 停留在当前位置
                container &&
                  setTimeout(() => {
                    // 计算新的滚动位置
                    const newScrollHeight = container.scrollHeight;
                    const scrollOffset = newScrollHeight - prevScrollHeight;
                    container.scrollTop = prevScrollTop + scrollOffset;
                  }, 100);
              }
            } else {
              setPage(page => Math.max(1, page - 1));
              console.warn('获取消息列表失败', { code, data });
            }
          } catch (error) {
            console.warn('获取消息列表失败', error);
          } finally {
            setIsLoading(false);
          }
        });
      }

      return fetchQueueRef.current.enqueue(tempPage);
    },
    [autoScroll, routerParams.chatSessionId, routerParams.tenantId]
  );

  const fetchLatestMessageList = useCallback(() => fetchMessageList(1), [fetchMessageList]);

  // 是否到达容器底部
  const isContainerAtBottom = (el: any) => {
    const containerHeight = el.clientHeight;
    const { scrollTop } = el;
    const { scrollHeight } = el;
    return containerHeight + scrollTop + 10 >= scrollHeight;
  };

  useEffect(() => {
    isReachBottom && updateMessageList();
  }, [isReachBottom]);

  const [answerLoading, setAnswerLoading] = useState<boolean>(false);
  const [isTimeout, setIsTimeout] = useState<boolean>(false); // 是否已超时
  const [thinkingHints, setThinkingHints] = useState<string[]>([]);
  // 走统一判据 ✓（`@/utils/conversationSocket.mjs` ✓，Task C2）：公开测试模式**忽略一切显式 base** ✗
  // （含历史遗留的 `NEXT_PUBLIC_AGENT_WS_BASE` ✗）、按 `window.location` 同源派生 ✓；
  // 其他模式保持既有优先级 ✓（override → 遗留 base → 同源 ✓）。SSR 下仍给空串 ✓。
  const wsBase =
    typeof window === 'undefined'
      ? ''
      : socketBase(
          window.location,
          process.env.NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE || process.env.NEXT_PUBLIC_AGENT_WS_BASE || '',
          process.env.NEXT_PUBLIC_CODEX_ACCESS_MODE,
        );
  // **走 V3 路由** ✓✓（2026-09-26 C4 真栈联调定论 ✓）：
  // 老地址 `/gaotu-assistant-agent/plus/chat/…/do` 是服务端的 **compat 循环** ✗，
  // 它回的信封是 `{type, content, end}` ✗——**没有 `turnId`/`protocolVersion`** ✓，
  // 而本页的 reducer（`conversationEvents.mjs` ✓）**只认 V1 事件** ✗ →
  // 于是进度事件被丢弃 ✓、界面上连回合块都建不出来 ✓（探针实证 ✓）。
  // `/ws/chat` 是 **V3 路由** ✓（服务端日志打 "v3 protocol" ✓），验证方式与老路由**完全相同** ✓
  // （同样校验 `ticket` + `chatSessionId` + Origin ✓，见 `_verify_conversation_access` ✓），
  // 且 C2 的 Nginx 配置里早就为它留了位置 ✓（`location = /ws/chat` + Upgrade 头 ✓）。
  const websocketUrl = `${wsBase}/ws/chat?chatSessionId=${routerParams.chatSessionId}`;

  // 心跳相关配置
  const HEARTBEAT_INTERVAL = 5000; // 心跳发送间隔：5秒
  const HEARTBEAT_TIMEOUT = 30000; // 心跳超时时间：30秒（超过这个时间没收到pong就认为失败）

  // 回答超时配置
  const ANSWER_TIMEOUT = 30000; // 回答超时时间：30秒（超过这个时间没收到回复就显示放弃等待按钮）

  // 心跳定时器引用（合并发送和检测功能）
  const heartbeatTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastPingTimeRef = useRef<number>(0);
  const lastPongTimeRef = useRef<number>(0);
  // 保存最新的连接状态和重连函数
  const isConnectedRef = useRef<boolean>(false);
  const reconnectRef = useRef<(() => void) | undefined>(undefined);
  const sendMessageRef = useRef<((message: any) => void) | undefined>(undefined);

  // 回答超时定时器引用
  const answerTimeoutTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 清除回答超时定时器
  const clearAnswerTimeout = useCallback(() => {
    if (answerTimeoutTimerRef.current) {
      clearTimeout(answerTimeoutTimerRef.current);
      answerTimeoutTimerRef.current = null;
    }
  }, []);

  const appendOptimisticUserMessage = useCallback(
    (content: string) => {
      optimisticMessageSeqRef.current += 1;
      const optimisticId = OPTIMISTIC_MESSAGE_ID_BASE + Date.now() + optimisticMessageSeqRef.current;
      setMessageList(prevList => {
        const optimisticAfterId = prevList.reduce((maxId, record) => {
          if (isOptimisticUserMessage(record)) {
            return maxId;
          }
          return Math.max(maxId, record.id || 0);
        }, 0);
        const optimisticMessage: IOptimisticMessage = {
          id: optimisticId,
          chatSessionId: +routerParams.chatSessionId,
          messageFrom: '1',
          contentType: 'TEXT',
          content,
          nerList: [],
          contentSegments: [{ type: 'text', content }],
          optimistic: true,
          optimisticAfterId,
        };
        return [...prevList, optimisticMessage].sort((a: IMessage, b: IMessage) => a.id - b.id);
      });
    },
    [routerParams.chatSessionId]
  );

  const appendAgentWsMessage = useCallback(
    (data: WebSocketMessage | string) => {
      const actionResult = parseConversationActionResult(data);
      if (actionResult) {
        applyConversationActionResult(actionResult);
        return;
      }
      const wsData = typeof data === 'string' ? { type: 'text', content: data } : data;
      const type = typeof wsData?.type === 'string' ? wsData.type : 'text';
      if (type === 'pong' || type === 'thinking') {
        return;
      }
      const contentValue = (wsData as any)?.content;
      if (contentValue === undefined || contentValue === null || contentValue === '') {
        return;
      }
      const contentType = ['pendingConfirmationCard', 'planningWorkspaceAction'].includes(type) ? 'CARD' : 'TEXT';
      const content =
        contentType === 'CARD' && typeof contentValue !== 'string'
          ? JSON.stringify(contentValue)
          : String(contentValue);
      optimisticMessageSeqRef.current += 1;
      const transientMessage: ITransientAgentMessage = {
        id: OPTIMISTIC_MESSAGE_ID_BASE + Date.now() + optimisticMessageSeqRef.current,
        chatSessionId: +routerParams.chatSessionId,
        messageFrom: '0',
        contentType,
        content,
        nerList: [],
        contentSegments: contentType === 'TEXT' ? [{ type: 'text', content }] : [],
        transient: true,
      };
      setMessageList(prevList => {
        const exists = prevList.some(
          item =>
            item.messageFrom === transientMessage.messageFrom &&
            item.contentType === transientMessage.contentType &&
            (item.content || '') === transientMessage.content
        );
        if (exists) {
          return prevList;
        }
        return [...prevList, transientMessage].sort((a: IMessage, b: IMessage) => a.id - b.id);
      });
    },
    [routerParams.chatSessionId]
  );

  // 重置回答加载状态
  const resetAnswerLoading = useCallback(() => {
    setAnswerLoading(false);
    setIsTimeout(false);
    setThinkingHints([]);
    clearAnswerTimeout();
  }, [clearAnswerTimeout]);

  const appendThinkingHint = useCallback((hint?: string) => {
    const normalizedHint = hint?.trim();
    if (!normalizedHint) {
      return;
    }
    setAnswerLoading(true);
    setThinkingHints([normalizedHint]);
  }, []);

  // ── 会话事件状态 ────────────────────────────────────────────────
  // ref 是同步的真相来源，state 只用于触发渲染：WS 回调里连续到达的事件
  // 如果只靠 setState 的 updater 串行化，回调返回后拿不到"处理完没有"。
  const conversationSessionId = String(
    (routerParams as any)?.chatSessionId || (routerParams as any)?.sessionId || '',
  );
  const conversationStateRef = useRef(createConversationState(conversationSessionId));
  const [conversationState, setConversationState] = useState(() =>
    createConversationState(conversationSessionId),
  );
  const localSequenceRef = useRef(0);
  // **续传游标** ✓：`(代际, 序号)`，只在页面还活着时有意义 ✓。
  // 刻意**不落盘** ✗✓——刷新会清掉 reducer 状态、却清不掉存储 ✗：带着"我看过到 N"
  // 的旧游标重连，服务端只会补一条尾巴 ✗，而页面其实什么状态都没有 ✗ →
  // 在飞回合的前半段永远回不来 ✓（F10 要的正是"整回合恢复" ✓）。
  const cursorRef = useRef<{ epoch: string; sequence: number } | null>(null);

  useEffect(() => {
    // 换会话就是换一条时间线：旧状态留着会让新会话页面上挂着上一个会话的答案。
    conversationStateRef.current = createConversationState(conversationSessionId);
    localSequenceRef.current = 0;
    cursorRef.current = null; // 游标属于那条时间线，换会话就必须作废
    setConversationState(conversationStateRef.current);
  }, [conversationSessionId]);

  const applyConversationEvent = useCallback((frame: unknown) => {
    if (!conversationSessionId) return null;
    localSequenceRef.current += 1;
    const event = toConversationEvent(frame, {
      sessionId: conversationSessionId,
      streamEpoch: 'local',
      sequence: localSequenceRef.current,
    });
    if (!event) return null;
    const base =
      conversationStateRef.current.sessionId === event.sessionId
        ? conversationStateRef.current
        : createConversationState(event.sessionId);
    const next = reduceConversation(base, event);
    // **帧 → 状态的可开关探针** ✓✓：这一层是"帧到了、界面却没建起来"这类问题的落点 ✓——
    // 实测靠它一次点名了两处（老信封/V1 混流判换代 ✓、本地帧触发缺口 ✓）。
    // 默认**关** ✓（每条帧一行会很吵 ✓）；在控制台执行
    // `localStorage.setItem('zhiyuan.conversationTrace','1')` 再刷新即可开 ✓。
    if (
      typeof window !== 'undefined' &&
      window.localStorage?.getItem('zhiyuan.conversationTrace') === '1'
    ) {
      console.log(
        '[conv] ' +
          JSON.stringify({
          rawType: (frame as { type?: string })?.type,
          isV1: isConversationV1Event(frame),
          type: (event as { type?: string })?.type,
          epoch: (event as { streamEpoch?: string })?.streamEpoch,
          seq: (event as { sequence?: number })?.sequence,
          stateSession: conversationStateRef.current.sessionId,
          stateEpoch: conversationStateRef.current.streamEpoch,
          stateSeq: conversationStateRef.current.lastSequence,
          eventSession: (event as { sessionId?: string })?.sessionId,
          applied: next !== base,
          needsResync: (next as { needsResync?: boolean })?.needsResync,
          turns: Object.keys((next as { turns?: object })?.turns || {}).length,
          }),
      );
    }
    if (next === base) return event;
    conversationStateRef.current = next;
    setConversationState(next);
    // 每次推进都跟着走 ✓：老信封（代际 `local`）拿不出游标 → 置空 ✓，
    // 免得把就地编的本地序号当成真游标发出去 ✗（见 `conversationCursor.mjs` ✓）。
    cursorRef.current = cursorFromState(next);
    if (next.needsResync) {
      // **这里以前只打一行 console.warn** ✗：用户看到的是"消息少了几条"，
      // 而他不知道该不该刷新 ✓。现在真的做重同步 ✓（与 `session.resync` 那条路收尾一致 ✓）：
      // **丢掉本地时间线** ✓（游标随之作废 ✓）、按消息历史整体对齐一次 ✓。
      // 丢掉是安全的：已结束的回合本来就在消息历史里 ✓，只有"在飞的那一轮"需要事件流 ✓，
      // 而它下一帧就会从新的基线重新建起来 ✓。
      console.warn('会话事件流需要重新同步：丢弃本地时间线，改按消息历史重建');
      conversationStateRef.current = createConversationState(conversationSessionId);
      cursorRef.current = null;
      setConversationState(conversationStateRef.current);
      fetchLatestMessageList();
    }
    return event;
  }, [conversationSessionId, fetchLatestMessageList]);

  // **提案的采纳/放弃** ✓：帧的形状**照既有那条** ✓（老的消息卡也是这么发的 ✓）——
  // `inputType: pendingConfirmation` + `conversationAction.{confirm,cancel}_proposal` ✓
  // + `expectedSourceVersion`（服务端据此判版本冲突 ✓，别用 DOM 里的号 ✗）
  // + `intent: 'explicit'`（区分"用户点的"与"顺手点的" ✓）。
  // **不新造协议** ✓：出站这一半 P2 那一轮就完整了 ✓，缺的只是把它接到 V1 的卡上 ✓。
  const handleProposalDecision = useCallback(
    async (
      proposal: { proposalRef?: string; sourceVersion?: number } | undefined,
      action: 'confirm' | 'cancel',
    ) => {
      const proposalRef = String(proposal?.proposalRef || '');
      if (!proposalRef) return;
      // **帧走纯函数** ✓（`conversationProtocol.mjs` ✓）——手拼过一次，结果是全静默 ✗✓：
      // `content` 塞了对象 ✓，而 schema 要求**空串** ✗ → 服务端回"消息格式错误" ✓ 且不记日志 ✓。
      await sendMessageRef.current?.(
        buildPendingConfirmationFrame({
          sessionId: conversationSessionId,
          userId: String((routerParams as any)?.userId || ''),
          action,
          proposalRef,
          sourceVersion: proposal?.sourceVersion,
          clientRequestId: stableClientRequestId('proposal', proposalRef),
        }),
      );
    },
    [conversationSessionId, routerParams],
  );

  const handleClarificationAnswer = useCallback(
    (requestId: string, answer: Record<string, unknown>, clientRequestId: string) => {
      // 交回服务端的形状必须与 A4 的合同一致：choice 走 answers、form 走 action+content，
      // 且 requestId 是服务端给的、客户端不得改写。
      sendMessageRef.current?.(
        buildClarificationAnswerFrame({
          sessionId: conversationSessionId,
          turnId:
            (Object.values(conversationStateRef.current.turns || {}) as any[]).find(
              turn => turn.clarifications && turn.clarifications[requestId],
            )?.id || '',
          requestId,
          answer,
          clientRequestId,
        }),
      );
    },
    [conversationSessionId],
  );

  const handleSteerTurn = useCallback((turnId: string, text: string) => {
    // 补充说明走 turnSteer：它是用户新增的一句话，不是"就地改模型的摘要"。
    // 回合已经结束时服务端会回 no_active_turn，页面据此提示用户另发一条。
    sendMessageRef.current?.(
      buildTurnSteerFrame({
        sessionId: conversationSessionId,
        turnId,
        text,
        clientRequestId: `steer-${turnId}-${text.length}`,
      }),
    );
  }, [conversationSessionId]);

  const handleInterruptTurn = useCallback((turnId: string) => {
    sendMessageRef.current?.(
      buildTurnInterruptFrame({
        sessionId: conversationSessionId,
        turnId,
        clientRequestId: `stop-${turnId}`,
      }),
    );
  }, [conversationSessionId]);

  // 每次连接尝试都取一张新票：票是一次性且 60 秒有效的，
  // 重连时复用旧票会被服务端拒掉，而那种失败看起来像"网络问题"。
  const authenticateForWebSocket = useCallback(async () => {
    const response: any = await fetchWsTicketApi(String(tenantId), {
      sessionId: String(routerParams.chatSessionId),
      botId: String(botId),
    });
    const ticket = response?.data?.ticket ?? response?.ticket;
    if (!ticket) {
      throw new Error('ws_ticket_missing');
    }
    // **续传游标挂在这里** ✓✓：`authenticate` 每次**连接尝试**都会被调一次 ✓
    //（hook 里用 `new URLSearchParams(params)` 拼进 URL ✓），于是带上去的就是
    // "连接那一刻"的游标 ✓。塞进 `websocketUrl` 反而会随每次渲染重算 ✗——
    // URL 一变 hook 就断连重连，直接掉进重连循环 ✗。
    // 没游标（刷新后 / 还没读到编号事件 / 走的是老信封）就**不带** ✓：
    // 服务端按"没有游标"处理 → 补整个当前回合 ✓，而不是只补一条尾巴 ✗。
    const params: Record<string, string> = { ticket: String(ticket) };
    const cursor = cursorRef.current;
    if (cursor) {
      params.epoch = cursor.epoch;
      params.since = String(cursor.sequence);
    }
    return params;
  }, [tenantId, botId, routerParams.chatSessionId]);

  const { sendMessage, disconnect, reconnect, isConnected } = useWebSocket(websocketUrl, {
    authenticate: authenticateForWebSocket,
    // V3 路由要求消息里带 tenant/bot ✓（老路由把它们写在路径里 ✓；见 hook 里的 withScope ✓）。
    tenantId,
    botId,
    onMessage(data, event) {
      if (typeof data === 'object' && data !== null && 'type' in data) {
        const wsData = data as IThinkingMessage;
        if (wsData.type === 'thinking') {
          appendThinkingHint(wsData.content);
          return;
        }
      }

      const conversationEvent = applyConversationEvent(data);
      if (conversationEvent) {
        // 进度只更新状态，**不重拉整页、不结束 loading**。
        // 以前任何一条非 pong 消息都会触发"重拉列表 + 结束转圈"，
        // 于是模型还在跑的时候用户已经看到转圈停了，而列表在被反复重拉。
        if (conversationEvent.type === 'turn.completed') {
          // 运行结束才是本地 loading 的终点；这时对齐一次持久化消息。
          resetAnswerLoading();
          fetchLatestMessageList();
        } else if (conversationEvent.type === 'session.resync') {
          // resync 重置了基线，列表必须整体对齐，否则页面会停在旧基线上。
          fetchLatestMessageList();
        } else if (
          conversationEvent.type === 'conversationAction.result' &&
          (conversationEvent.payload as any)?.actionStatus === 'applied'
        ) {
          // 只有**已生效**才对齐：确认中、已取消、过期都不需要重拉，
          // 而"确认中"去重拉会让用户以为已经生效了。
          resetAnswerLoading();
          fetchLatestMessageList();
          // 工作区也要跟着刷新：正式方案变了而工作区停旧版本，
          // 用户会照着旧方案继续操作。
          setFetchFlag(prev => prev + 1);
        }
        return;
      }

      const workspaceIntent = parseWorkspaceIntentPayload(data);
      if (workspaceIntent) {
        onWorkspaceIntent?.(workspaceIntent);
        if (workspaceIntent.refresh) {
          setFetchFlag(prev => prev + 1);
        }
      }

      // 判断是否是 pong 消息
      if (typeof data === 'object' && data !== null && 'type' in data && data.type === 'pong') {
        // 更新最后收到 pong 的时间
        lastPongTimeRef.current = Date.now();
        // pong 消息不需要执行 fetchMessageList 和 setAnswerLoading
        return;
      }

      // 其他消息才需要重新拉取消息列表和更新加载状态
      appendAgentWsMessage(data);
      fetchLatestMessageList();
      resetAnswerLoading();
    },
    onClose(event) {
      // 连接断开时重置回答加载状态
      console.log('🔌 WebSocket closed, resetting answer loading state');
      resetAnswerLoading();
    },
    onError(error) {
      // 连接错误时重置回答加载状态
      console.error('❌ WebSocket error, resetting answer loading state', error);
      resetAnswerLoading();
    },
  });

  // 心跳逻辑（合并发送和检测功能，使用一个定时器）
  useEffect(() => {
    // 心跳处理函数：发送心跳 + 检测超时
    const handleHeartbeat = () => {
      const now = Date.now();

      // 1. 检测心跳是否超时（每次执行都检查）
      if (isConnectedRef.current && lastPingTimeRef.current > 0) {
        const timeSinceLastPing = now - lastPingTimeRef.current;
        const hasReceivedPong = lastPongTimeRef.current >= lastPingTimeRef.current;

        // 如果发送了 ping 但超过超时时间还没收到对应的 pong，认为心跳失败
        if (!hasReceivedPong && timeSinceLastPing > HEARTBEAT_TIMEOUT) {
          console.warn('⚠️ 心跳超时，尝试重新连接');
          // 清理定时器
          if (heartbeatTimerRef.current) {
            clearInterval(heartbeatTimerRef.current);
            heartbeatTimerRef.current = null;
          }
          // 重置时间戳
          lastPingTimeRef.current = 0;
          lastPongTimeRef.current = 0;
          // 触发重连
          reconnectRef.current?.();
          return;
        }
      }

      // 2. 如果连接已建立，发送心跳
      if (isConnectedRef.current && sendMessageRef.current) {
        const pingMessage = {
          sessionId: routerParams.chatSessionId,
          userId: routerParams.userId || '',
          content: '',
          inputType: 'ping',
          timestamp: now,
        };
        lastPingTimeRef.current = now;
        sendMessageRef.current(pingMessage);
        console.log('💓 发送心跳 ping:', pingMessage);
      }
    };

    if (!isConnected) {
      // 连接断开时，清理心跳定时器
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
      return;
    }

    // 连接建立后，立即执行一次（发送心跳 + 检测超时）
    handleHeartbeat();

    // 设置定时器：每5秒执行一次（发送心跳 + 检测超时）
    heartbeatTimerRef.current = setInterval(() => {
      handleHeartbeat();
    }, HEARTBEAT_INTERVAL);

    // 清理函数
    return () => {
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
    };
  }, [isConnected, routerParams.chatSessionId, routerParams.userId]);

  // 更新 ref 值，确保心跳定时器能访问到最新的状态
  useEffect(() => {
    isConnectedRef.current = isConnected;
    reconnectRef.current = reconnect;
    sendMessageRef.current = sendMessage;
  }, [isConnected, reconnect, sendMessage]);

  useEffect(() => {
    activeChatSessionIdRef.current = routerParams.chatSessionId;
    fetchQueueRef.current = null;
    prevMessageListRef.current = [];
    pageRef.current = 1;
    itemRefs.current = [];
    optimisticMessageSeqRef.current = 0;
    setMessageList([]);
    setWsMessageList([]);
    setCheckedMap({});
    setPage(1);
    setTotal(0);
    setIsMore(false);
    setIsReachBottom(true);
    setAutoScroll(true);
    setUserInput('');
    setEntityCardList?.({});
    resetAnswerLoading();
    fetchMessageList(1);
  }, [routerParams.chatSessionId, routerParams.tenantId]);

  useEffect(() => {
    // 清理函数
    return () => {
      disconnect?.();
      // 清理心跳定时器
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
      // 清理回答超时定时器
      clearAnswerTimeout();
    };
  }, [disconnect, clearAnswerTimeout]);

  useEffect(() => {
    if (scrollEleIndex !== -1 && scrollEleIndex !== undefined) {
      itemRefs.current?.[scrollEleIndex]?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
      setScrollEleIndex(-1);
    }
  }, [scrollEleIndex]);

  const handleAddKeywordEntity = async (message: IMessage, content: TextSegment) => {
    console.log('点击添加', message, content);
    if (content.nerItem) {
      const { data, code } = await getEntityPropertyAnalyzeApi(routerParams.tenantId, {
        message_ner_id: content.nerItem.id,
      });
      if (code === 0 && data) {
        const arr = {
          id: content.nerItem.id,
          keyword: content.content,
          content: data,
          baike_tags: [content.nerItem],
          last: true,
        };
        //请求接口
        setEntityCardList?.((prevState: any) => {
          if (message?.id in prevState) {
            return {
              ...prevState,
              [message.id]: [
                ...new Set(
                  [
                    ...prevState?.[message.id]
                      .filter((item: any) => item.id !== content?.nerItem?.id)
                      .map((item: any) => ({
                        ...item,
                        last: false,
                      })),
                    arr,
                  ].map(item => JSON.stringify(item))
                ),
              ].map(str => JSON.parse(str)),
            };
          } else if (Object.keys(prevState)?.length > 4) {
            const newObj = Object.fromEntries(Object.entries(prevState).slice(0, -1));
            return { [message?.id]: [arr], ...newObj };
          } else {
            return { [message?.id]: [arr], ...prevState };
          }
        });
      }
    }
  };



  const bottomRef = useRef<HTMLDivElement>(null);

  const handleSendMsg = async () => {
    if (doChatRights && doChatRights.canOperate === false) {
      Modal.info({
        title: '提示',
        content: doChatRights.reason || '当前权益不足，无法继续此操作',
      });
      return;
    }
    if (answerLoading) {
      message.warning('正在生成中，请稍后再试');
      return;
    }
    const sentText = userInput?.trim();
    if (sentText) {
      appendOptimisticUserMessage(sentText);
      sendMessage?.({
        sessionId: routerParams.chatSessionId,
        userId: routerParams.userId || '',
        content: sentText,
        inputType: 'text',
      });
      setUserInput('');

      setAnswerLoading(true);
      setIsTimeout(false); // 重置超时状态
      setThinkingHints([]);

      // 清除之前的超时定时器（如果有）
      clearAnswerTimeout();

      // 设置新的超时定时器
      answerTimeoutTimerRef.current = setTimeout(() => {
        console.warn('⚠️ 回答超时，显示放弃等待按钮');
        // 超时后只设置超时状态，不自动重置加载状态，让用户选择是否放弃等待
        setIsTimeout(true);
        message.warning('等待回复超时，您可以继续等待或放弃等待');
      }, ANSWER_TIMEOUT);

      // 使用 scrollToBottom 替代 scrollIntoView，避免移动端 overflow 容器内滚动失效
      scrollToBottom();
    }
  };

  const handleSendPresetMessage = async (preset: string) => {
    if (!preset.trim()) {
      return;
    }
    setUserInput(preset);
    if (doChatRights && doChatRights.canOperate === false) {
      Modal.info({
        title: '提示',
        content: doChatRights.reason || '当前权益不足，无法继续此操作',
      });
      return;
    }
    if (answerLoading) {
      message.warning('正在生成中，请稍后再试');
      return;
    }
    const sentText = preset.trim();
    appendOptimisticUserMessage(sentText);
    sendMessage?.({
      sessionId: routerParams.chatSessionId,
      userId: routerParams.userId || '',
      content: sentText,
      inputType: 'text',
    });
    setUserInput('');

    setAnswerLoading(true);
    setIsTimeout(false);
    setThinkingHints([]);
    clearAnswerTimeout();
    answerTimeoutTimerRef.current = setTimeout(() => {
      console.warn('⚠️ 回答超时，显示放弃等待按钮');
      setIsTimeout(true);
      message.warning('等待回复超时，您可以继续等待或放弃等待');
    }, ANSWER_TIMEOUT);
    scrollToBottom();
  };

  // 手动放弃等待
  const handleCancelWaiting = () => {
    resetAnswerLoading();
    message.info('已放弃等待');
  };

  // 收到新消息后滚动到底部（兜底逻辑，确保移动端能正确滚动）
  const prevMessageCountRef = useRef(0);
  useEffect(() => {
    const prevCount = prevMessageCountRef.current;
    const currCount = messageList.length;
    prevMessageCountRef.current = currCount;
    // 消息数量增加且用户在底部或正在等待回复时，滚动到底部
    if (currCount > prevCount && (isReachBottom || answerLoading)) {
      scrollToBottom();
    }
  }, [messageList.length, isReachBottom, answerLoading]);

  useEffect(() => {
    // 当 messageList 变化时，根据 message 里返回的 items 里的 selected 字段来判断是否被选择
    setCheckedMap(prev => {
      const newMap = { ...prev };
      messageList.forEach(msg => {
        const contentObj = msg.contentType === 'CARD' ? parseCardContent(msg.content) : null;
        if (isIntentConfirmCard(contentObj)) {
          const items = contentObj?.items || [];
          // 如果之前没有、或长度不一致，则根据 items 中的 selected 字段初始化
          if (!Array.isArray(newMap[msg.id]) || newMap[msg.id].length !== items.length) {
            newMap[msg.id] = items.map((item: any) => item.selected ?? true);
          }
        }
      });
      return newMap;
    });
  }, [messageList]);

  useEffect(() => {
    if (answerLoading) {
      scrollToBottom();
    }
  }, [answerLoading, thinkingHints.length, isTimeout]);

  const handleGenerateClick = async (msg?: IMessage) => {
    try {
      const contentObj = msg ? parseCardContent(msg.content) : null;
      if (!contentObj) {
        return;
      }

      // 从当前消息提取出勾选的 item
      let selected: any[] = [];
      let selectedIndexes: number[] = [];
      if (isIntentConfirmCard(contentObj) && contentObj.items) {
        const indexedItems = contentObj.items
          .map((item: any, index: number) => ({ ...item, index }))
          // 仅保留勾选项（若某条 message 没有对应 checkedMap，则默认视为 true）
          .filter((item: any) => checkedMap[msg!.id]?.[item.index] ?? true);
        selectedIndexes = indexedItems.map((item: any) => item.index);
        selected = indexedItems.map((item: any) => {
          return item.value;
        });
      }
      console.log('点击生成获取参数', selected);

      setAnswerLoading(true);
      setIsTimeout(false);
      setThinkingHints([]);
      clearAnswerTimeout();
      answerTimeoutTimerRef.current = setTimeout(() => {
        console.warn('⚠️ 回答超时，显示放弃等待按钮');
        setIsTimeout(true);
        message.warning('等待回复超时，您可以继续等待或放弃等待');
      }, ANSWER_TIMEOUT);
      scrollToBottom();

      await sendMessage?.({
        sessionId: routerParams.chatSessionId,
        userId: routerParams.userId || '',
        content:
          contentObj.type === 'planEditPopup'
            ? '采纳'
            : {
                action: '采纳',
                message_id: msg?.id,
                selected,
              },
        inputType:
          contentObj.type === 'planEditPopup' || contentObj.type === 'intentDetectPopup'
            ? 'text'
            : 'intentSelect',
      });

      if (isIntentConfirmCard(contentObj) && msg?.id) {
        markIntentCardHandled(msg.id, selectedIndexes, selected.length > 0);
      }

      // 新确认协议下，卡片点击只创建/触发待确认动作；工作区刷新由后端
      // planningWorkspaceAction 统一驱动，避免本地抢先刷新造成重复跳转。
    } catch (err) {
      resetAnswerLoading();
      console.error('消息发送失败', err);
    }

  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      if (event.shiftKey) {
        // Shift + Enter: 换行
        event.preventDefault();
        setUserInput(prev => prev + '\n');
      } else {
        // Enter: 发送消息
        event.preventDefault();
        handleSendMsg();
      }
    }
  };
  const [feedbackMap, setFeedbackMap] = useState<Record<number, number>>({});

  const parseCardContent = (content: string): IIntentCardContent | null => {
    try {
      return JSON.parse(content);
    } catch (error) {
      console.warn('解析 CARD 消息失败', error);
      return null;
    }
  };

  const markIntentCardHandled = (
    messageId: number,
    selectedIndexes: number[],
    accepted: boolean
  ) => {
    setMessageList(prevList =>
      prevList.map(item => {
        if (item.id !== messageId || item.contentType !== 'CARD') {
          return item;
        }
        const contentObj = parseCardContent(item.content);
        if (!isIntentConfirmCard(contentObj)) {
          return item;
        }
        return {
          ...item,
          content: JSON.stringify({
            ...contentObj,
            clickable: false,
            clicked: accepted,
            click_type: accepted ? 1 : 0,
            items: Array.isArray(contentObj?.items)
              ? contentObj?.items.map((cardItem, index) => ({
                  ...cardItem,
                  selected: selectedIndexes.includes(index),
                }))
              : contentObj?.items,
          }),
        };
      })
    );
  };

  const applyConversationActionResult = (result: any) => {
    const actionResult = result?.actionResult;
    setMessageList(prevList =>
      prevList.map(item => {
        if (item.contentType !== 'CARD') return item;
        const contentObj = parseCardContent(item.content);
        if (!isPendingConfirmationCard(contentObj)) return item;
        const updated = applyPendingActionResult(contentObj, actionResult);
        if (updated === contentObj) return item;
        return {
          ...item,
          content: JSON.stringify(updated),
        };
      })
    );
    resetAnswerLoading();
  };

  const renderImpactBlock = (impact?: string, impactTitle?: string) => {
    const impactText = impact?.trim();
    if (!impactText) {
      return null;
    }

    return (
      <div className={style.analysisTextBlock}>
        {impactTitle ? <div className={style.analysisTextTitle}>{impactTitle}</div> : null}
        <div className={style.analysisTextBody}>
          {impactText.split('\n').map((line, index) => (
            <div key={`${line}-${index}`} className={style.analysisTextLine}>
              {line}
            </div>
          ))}
        </div>
      </div>
    );
  };

  const genericIntentAnalysisItems = new Set([
    '这轮会重点看当前方案里是否存在需要避开的内容，以及候选里是否还有可替换机会。',
    '这轮会重点看当前方案里是否已有贴近方向，以及候选里还有哪些值得继续关注的机会。',
    '方案外如果还有更贴近这个方向的候选机会，也会一起作为补充参考。',
    '这类想法不会立刻改动候选结果，但会影响我后面怎么帮你分析和给建议。',
    '如果这是必须避开的报考条件，我可以继续帮你找出方案里还需要避开的地方。',
    '你也可以先去工作台候选区看看，按这个要求筛完之后还剩哪些机会。',
    '如果你愿意把它当成偏好，我可以继续帮你看现在的方案哪里比较贴近、哪里还能补强。',
    '如果你现在只是先了解，也可以继续问我这个方向适不适合你。',
    '下一步可以先定位方案里不符合这条要求的志愿，再决定是否替换或移除。',
    '下一步可以继续看这份方案和你的想法有多匹配，或者让我给出具体调整建议。',
  ]);

  const normalizeIntentAnalysisItem = (item?: string) => {
    const text = `${item || ''}`.trim().replace(/^-+\s*/, '').trim();
    if (!text || genericIntentAnalysisItems.has(text)) {
      return '';
    }
    if (text.startsWith('**') && text.endsWith('**')) {
      return '';
    }
    return text;
  };

  const collectCompactIntentAnalysisItems = (analysis?: IIntentAnalysisContent) => {
    if (!analysis) {
      return [];
    }
    const result: string[] = [];
    const seen = new Set<string>();
    const groups = [
      analysis.currentPlanConflict,
      analysis.currentPlanFit,
      analysis.candidateOpportunity,
    ];
    groups.forEach(group => {
      if (!Array.isArray(group)) {
        return;
      }
      group.forEach(rawItem => {
        if (result.length >= 2) {
          return;
        }
        const item = normalizeIntentAnalysisItem(rawItem);
        if (!item || seen.has(item)) {
          return;
        }
        result.push(item);
        seen.add(item);
      });
    });
    return result;
  };

  const renderIntentAnalysisBlock = (
    analysis?: IIntentAnalysisContent,
    _impactTitle?: string
  ) => {
    const compactItems = collectCompactIntentAnalysisItems(analysis);
    if (compactItems.length === 0) {
      return null;
    }

    return (
      <div className={style.analysisTextBlock}>
        <div className={style.analysisTextTitle}>影响</div>
        <div className={style.analysisTextList}>
          {compactItems.map((item, index) => (
            <div key={`${item}-${index}`} className={style.analysisTextListItem}>
              <span className={style.analysisTextBullet}>-</span>
              <span className={style.analysisTextListItemContent}>{item}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const handleInterestActionClick = async (msg?: IMessage, action?: IInterestAction) => {
    if (!action?.actionType) {
      return;
    }
    try {
      setAnswerLoading(true);
      setIsTimeout(false);
      setThinkingHints([]);
      clearAnswerTimeout();
      answerTimeoutTimerRef.current = setTimeout(() => {
        console.warn('⚠️ 回答超时，显示放弃等待按钮');
        setIsTimeout(true);
        message.warning('等待回复超时，您可以继续等待或放弃等待');
      }, ANSWER_TIMEOUT);
      scrollToBottom();

      await sendMessage?.({
        sessionId: routerParams.chatSessionId,
        userId: routerParams.userId || '',
        content: {
          action: 'interestAction',
          actionType: action.actionType,
          message_id: msg?.id,
        },
        inputType: 'intentSelect',
      });
      await fetchLatestMessageList();
    } catch (error) {
      resetAnswerLoading();
      console.error('兴趣分析动作发送失败', error);
    }
  };

  const handleWorkspaceCardClick = (contentObj: IIntentCardContent) => {
    const targetView = normalizeWorkspaceTargetView(contentObj.targetView);
    const refreshTargets = normalizeWorkspaceRefreshTargets(contentObj as Record<string, any>);
    if (!targetView && refreshTargets.length === 0) {
      return;
    }
    onWorkspaceIntent?.({
      targetTab: 'volunteer',
      targetView: targetView || undefined,
      refreshTargets,
      volunteerIds: contentObj.volunteerIds || [],
      refresh: contentObj.refresh,
      preserveView: contentObj.preserveView,
      silent: contentObj.silent,
      candidateFilters: contentObj.candidateFilters,
    });
  };

  const handlePendingConfirmationClick = async (
    msg: IMessage,
    action: 'confirm' | 'cancel'
  ) => {
    const contentObj = parseCardContent(msg.content);
    if (!isPendingConfirmationCard(contentObj) || contentObj?.clickable === false) {
      return;
    }
    const cardContent = contentObj as IIntentCardContent;
    try {
      setAnswerLoading(true);
      setIsTimeout(false);
      setThinkingHints([]);
      clearAnswerTimeout();
      answerTimeoutTimerRef.current = setTimeout(() => {
        console.warn('⚠️ 回答超时，显示放弃等待按钮');
        setIsTimeout(true);
        message.warning('等待回复超时，您可以继续等待或放弃等待');
      }, ANSWER_TIMEOUT);
      scrollToBottom();

      await sendMessage?.({
        sessionId: routerParams.chatSessionId,
        userId: routerParams.userId || '',
        content: {
          action,
          kind: cardContent.kind || 'plan_mutation',
          pendingId: cardContent.pendingId,
          message_id: msg.id,
        },
        inputType: 'pendingConfirmation',
        conversationAction: {
          actionType: action === 'confirm' ? 'confirm_proposal' : 'cancel_proposal',
          proposalRef: cardContent.proposalRef || cardContent.pendingId,
          expectedSourceVersion: cardContent.sourceVersion,
          intent: 'explicit',
        },
      });
    } catch (error) {
      resetAnswerLoading();
      console.error('待采纳内容操作失败', error);
    }
  };

  // 消息反馈
  const handleClickFeedback = (feedback: number, type: 'link' | 'dislike', messageId: number) => {
    let newFeedback = 0;
    if (type === 'link') {
      newFeedback = feedback === 1 || feedbackMap[messageId] === 1 ? 0 : 1;
    } else if (type === 'dislike') {
      newFeedback = feedback === -1 || feedbackMap[messageId] === -1 ? 0 : -1;
    }
    getFeedbackApi(tenantId, { messageId, feedback: newFeedback }).then(res => {
      if (res.code === 0) {
        setFeedbackMap(prevState => ({ ...prevState, [messageId]: newFeedback }));
        // message.success('反馈成功');
      }
    });
    console.log('消息反馈', feedback, newFeedback);
  };

  const displayMessageList = messageList.filter((record, index, records) => {
    if (isLegacyAutoPlanPrompt(record, index, records)) {
      return false;
    }
    if (record.messageFrom === '0' && record.contentType === 'CARD') {
      return !isWorkspaceActionCard(parseCardContent(record.content));
    }
    return true;
  });
  const activePendingCardMessageId = displayMessageList.reduce<number | null>((latestId, record) => {
    if (record.messageFrom !== '0' || record.contentType !== 'CARD') {
      return latestId;
    }
    const contentObj = parseCardContent(record.content);
    if (
      isPendingConfirmationCard(contentObj) &&
      contentObj?.clickable !== false &&
      (contentObj?.status || 'active') === 'active'
    ) {
      return record.id;
    }
    return latestId;
  }, null);
  const getEffectivePendingCardContent = (
    record: IMessage,
    contentObj: IIntentCardContent
  ): IIntentCardContent => {
    if (
      isPendingConfirmationCard(contentObj) &&
      contentObj?.clickable !== false &&
      (contentObj?.status || 'active') === 'active' &&
      activePendingCardMessageId !== null &&
      record.id !== activePendingCardMessageId
    ) {
      return {
        ...contentObj,
        clickable: false,
        status: 'replaced',
      };
    }
    return contentObj;
  };
  const quickReplyList = quickReplyActions || [];
  const hasUserStartedConversation = displayMessageList.some(
    record =>
      record.messageFrom === '1' &&
      record.contentType === 'TEXT' &&
      Boolean((record.content || '').trim()) &&
      !isStructuredIntentSelectEcho(record)
  );
  const shouldShowQuickReplies =
    quickReplyList.length > 0 &&
    !answerLoading &&
    (alwaysShowQuickReplyActions || !hasUserStartedConversation);

  return (
    <div className={style.messagePanel}>
      <div
        className={style.messageContainer}
        onScroll={e => {
          const container = e.target as HTMLDivElement;
          if (container.scrollTop === 0 && !isLoading && isMore) {
            setPage(prevPage => {
              const nextPage = prevPage + 1;
              fetchMessageList(nextPage);
              return nextPage;
            });
          }
          setIsReachBottom(isContainerAtBottom(container));
        }}
        ref={messageContainerRef}
      >
        <Spin spinning={isLoading} tip="加载中...">
          {displayMessageList.length <= 0 && !isLoading && <Empty />}
          {displayMessageList.length > 0 && (
            <div className={style.loadMore}>
              {isMore ? (isLoading ? '加载中...' : '下拉加载更多') : '已经没有更多消息了~'}
            </div>
          )}
          {displayMessageList.length > 0 &&
            displayMessageList.map((message, index) => (
              <div
                ref={el => {
                  itemRefs.current[message.id] = el;
                }}
                // eslint-disable-next-line react/no-array-index-key
                key={message.id}
                // e2e 钩子 ✓（Task C4）：**答案落定后**才带这个 testid ✓——
                // 还在 `answerLoading` 时它不存在 ✓，所以"终态没到"那条断言才断得实 ✓。
                // 前提：每个用例开**独立会话** ✓（任务书要求 ✓），否则历史里会有多条 ✓。
                data-testid={
                  message.messageFrom === '0' && !answerLoading ? 'assistant-final' : undefined
                }
                className={`${style.messageBubble} ${style.aiMessage}`}
              >
                <div>
                  {message.messageFrom === '0' ? (
                    <Row style={{ flexWrap: 'nowrap' }} gutter={8}>
                      <Col span={24}>
                        <Card>
                          <div>
                            {message.contentType === 'TEXT' && (
                              <>
                                <div
                                  className="markdownBody"
                                  dangerouslySetInnerHTML={{
                                    __html: renderMarkdown(message.content || ''),
                                  }}
                                />

                                <div className={style.feekback}>
                                  {/* feedback字段//0：无反馈；1：正反馈；-1：负反馈。 */}
                                  <LikeOutlined
                                    onClick={() =>
                                      handleClickFeedback(message.feedback || 0, 'link', message.id)
                                    }
                                    style={{
                                      color:
                                        message.feedback === 1 || feedbackMap[message.id] === 1
                                          ? '#FF443D'
                                          : '#000',
                                    }}
                                  />
                                  <DislikeOutlined
                                    onClick={() =>
                                      handleClickFeedback(
                                        message.feedback || 0,
                                        'dislike',
                                        message.id
                                      )
                                    }
                                    style={{
                                      color:
                                        message.feedback === -1 || feedbackMap[message.id] === -1
                                          ? '#FF443D'
                                          : '#000',
                                    }}
                                  />
                                </div>
                              </>
                            )}
                            {message.contentType === 'CARD' &&
                              (() => {
                                const contentObj = parseCardContent(message.content);
                                if (!contentObj) {
                                  return <div style={{ whiteSpace: 'break-spaces' }}>{message.content}</div>;
                                }
                                if (contentObj.type === 'planningWorkspaceAction') {
                                  if (!normalizeWorkspaceTargetView(contentObj.targetView)) {
                                    return null;
                                  }
                                  if (contentObj.silent) {
                                    return null;
                                  }
                                  const fallbackCopy = workspaceActionFallbackCopy(contentObj);
                                  return (
                                    <div className={style.workspaceActionCard}>
                                      <div className={style.workspaceActionTitle}>
                                        {contentObj.title || fallbackCopy.title}
                                      </div>
                                      {contentObj.content || fallbackCopy.content ? (
                                        <div className={style.workspaceActionContent}>
                                          {contentObj.content || fallbackCopy.content}
                                        </div>
                                      ) : null}
                                      {renderImpactBlock(contentObj.impact, contentObj.impactTitle)}
                                      <Button
                                        className={style.generateButton}
                                        onClick={() => handleWorkspaceCardClick(contentObj)}
                                        size="small"
                                      >
                                        {contentObj.actionText || fallbackCopy.actionText}
                                      </Button>
                                    </div>
                                  );
                                }
                                if (isPendingConfirmationCard(contentObj)) {
                                  const effectiveContentObj = getEffectivePendingCardContent(
                                    message,
                                    contentObj
                                  );
                                  const cardDisabled =
                                    effectiveContentObj?.clickable === false ||
                                    ['applying', 'applied', 'cancelled', 'replaced', 'expired', 'stale_state', 'failed'].includes(
                                      effectiveContentObj?.status || ''
                                    );
                                  let statusText = '';
                                  let badgeText = '待确认';
                                  if (effectiveContentObj?.status === 'applied' || effectiveContentObj?.clicked) {
                                    statusText =
                                      effectiveContentObj?.kind === 'intent_change' ? '已采纳' : '已确认';
                                    badgeText =
                                      effectiveContentObj?.kind === 'intent_change' ? '已采纳' : '已生效';
                                  } else if (effectiveContentObj?.status === 'cancelled') {
                                    statusText =
                                      effectiveContentObj?.kind === 'intent_change' ? '未采纳' : '已取消';
                                    badgeText =
                                      effectiveContentObj?.kind === 'intent_change' ? '未采纳' : '已取消';
                                  } else if (effectiveContentObj?.status === 'replaced') {
                                    statusText = '已被新的确认卡替代';
                                    badgeText = '已替代';
                                  } else if (effectiveContentObj?.status === 'expired') {
                                    statusText = '已失效';
                                    badgeText = '已失效';
                                  } else if (effectiveContentObj?.status === 'applying') {
                                    statusText = '正在执行，请等待执行结果';
                                    badgeText = '执行中';
                                  } else if (effectiveContentObj?.status === 'stale_state') {
                                    statusText = '方案已变化，请重新生成预览';
                                    badgeText = '需重新确认';
                                  } else if (effectiveContentObj?.status === 'failed') {
                                    statusText = '未能确认执行结果，请刷新后检查方案';
                                    badgeText = '未完成';
                                  }
                                  return (
                                    <div className={style.pendingConfirmationCard}>
                                      <div className={style.pendingConfirmationHeader}>
                                        <span className={style.pendingConfirmationBadge}>{badgeText}</span>
                                        <div className={style.pendingConfirmationTitle}>
                                          {effectiveContentObj.title || '请确认本次方案调整'}
                                        </div>
                                      </div>
                                      {effectiveContentObj.summary ? (
                                        <div className={style.pendingConfirmationContent}>
                                          {effectiveContentObj.summary}
                                        </div>
                                      ) : null}
                                      {effectiveContentObj.content &&
                                      effectiveContentObj.content !== effectiveContentObj.summary ? (
                                        <div className={style.pendingConfirmationContent}>
                                          {effectiveContentObj.content}
                                        </div>
                                      ) : null}
                                      {renderImpactBlock(effectiveContentObj.impact, effectiveContentObj.impactTitle)}
                                      {statusText ? (
                                        <div className={style.pendingConfirmationStatus}>{statusText}</div>
                                      ) : (
                                        <div className={style.pendingConfirmationActions}>
                                          <Button
                                            className={style.pendingPrimaryButton}
                                            size="small"
                                            disabled={cardDisabled || answerLoading}
                                            onClick={() => handlePendingConfirmationClick(message, 'confirm')}
                                          >
                                            <CheckCircleOutlined />
                                            {effectiveContentObj.confirmText || '确认执行'}
                                          </Button>
                                          <Button
                                            className={style.pendingSecondaryButton}
                                            size="small"
                                            disabled={cardDisabled || answerLoading}
                                            onClick={() => handlePendingConfirmationClick(message, 'cancel')}
                                          >
                                            <CloseCircleOutlined />
                                            {effectiveContentObj.cancelText || '暂不执行'}
                                          </Button>
                                        </div>
                                      )}
                                    </div>
                                  );
                                }
                                const isButtonDisabled =
                                  !contentObj?.clickable ||
                                  (contentObj?.clicked && contentObj?.clickable);

                                // 根据 clickable 和 clicked 状态决定按钮文案
                                let buttonText = '采纳';
                                if (!contentObj?.clickable) {
                                  buttonText = contentObj?.clicked ? '您已采纳' : '您未采纳';
                                }

                                return (
                                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                                    <div style={{ whiteSpace: 'break-spaces' }}>
                                      {contentObj?.title}
                                    </div>
                                    {isIntentAnalysisCard(contentObj)
                                      ? renderIntentAnalysisBlock(
                                          contentObj?.analysis,
                                          contentObj?.impactTitle
                                        ) || renderImpactBlock(contentObj?.impact, contentObj?.impactTitle)
                                      : renderImpactBlock(contentObj?.impact, contentObj?.impactTitle)}
                                    {Array.isArray(contentObj?.existing_items) &&
                                      contentObj?.existing_items?.length > 0 && (
                                        <div
                                          style={{
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: 4,
                                            margin: '8px 0',
                                          }}
                                        >
                                          {contentObj?.existing_items?.map(
                                            (existingItem: any, existingIndex: number) => (
                                              <div
                                                key={`existing-${existingIndex}`}
                                                style={{ whiteSpace: 'break-spaces', color: '#8C8C8C' }}
                                              >
                                                {existingItem?.content}
                                              </div>
                                            )
                                          )}
                                        </div>
                                      )}

                                    {isIntentConfirmCard(contentObj) &&
                                      contentObj?.items?.map(
                                        (itemContent: any, itemIndex: number) => {
                                          const isChecked = checkedMap[message.id]?.[itemIndex] ?? true;
                                          return (
                                            <div
                                              key={itemIndex}
                                              style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: 8,
                                                marginBlock: 4,
                                              }}
                                            >
                                              <Checkbox
                                                checked={isChecked}
                                                disabled={isButtonDisabled}
                                                onChange={e => {
                                                  const checked = e.target.checked;
                                                  setCheckedMap(prev => {
                                                    const prevList = prev[message.id]
                                                      ? [...prev[message.id]]
                                                      : [];
                                                    // 确保长度足够
                                                    if (prevList.length <= itemIndex) {
                                                      const contentItems = contentObj?.items || [];
                                                      while (prevList.length < contentItems.length)
                                                        prevList.push(true);
                                                    }
                                                    prevList[itemIndex] = checked;
                                                    return { ...prev, [message.id]: prevList };
                                                  });
                                                }}
                                              />
                                              <div style={{ whiteSpace: 'break-spaces' }}>
                                                {itemContent.content}
                                              </div>
                                            </div>
                                          );
                                        }
                                      )}

                                    {isIntentConfirmCard(contentObj) ? (
                                      <Button
                                        className={style.generateButton}
                                        onClick={() => handleGenerateClick(message)}
                                        disabled={isButtonDisabled}
                                        size="small"
                                      >
                                        {buttonText}
                                      </Button>
                                    ) : isInterestAnalysisOnlyCard(contentObj) &&
                                      Array.isArray(contentObj?.actions) &&
                                      contentObj.actions.length > 0 ? (
                                      <div className={style.interestActionRow}>
                                        {contentObj.actions.map((action, actionIndex) => (
                                          <Button
                                            key={`${message.id}-interest-action-${actionIndex}`}
                                            className={style.interestActionButton}
                                            size="small"
                                            disabled={answerLoading}
                                            onClick={() => handleInterestActionClick(message, action)}
                                          >
                                            {action.label}
                                          </Button>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>
                                );
                              })()}
                          </div>
                        </Card>
                      </Col>
                    </Row>
                  ) : (
                    <Row justify="end">
                      <div
                        style={{
                          padding: 8,
                          background: '#FF443D',
                          color: '#fff',
                          borderRadius: 8,
                          // whiteSpace: 'break-spaces',
                          wordBreak: 'break-all',
                          maxWidth: '70%',
                        }}
                        className="markdownBody"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content || '') }}
                      />
                    </Row>
                  )}
                </div>
              </div>
            ))}
          {answerLoading && (
            <div className={style.thinkingContainer}>
              <div className={style.thinkingContent}>
                <div className={style.thinkingLabel}>正在分析</div>
                <div className={style.thinkingCurrentHint}>
                  <TypingAnimation text={thinkingHints[thinkingHints.length - 1] || '正在处理你的问题'} />
                </div>
              </div>
              {isTimeout && (
                <div className={style.thinkingTimeoutRow}>
                  <span className={style.thinkingTimeoutText}>等待时间较长，可以继续等待。</span>
                  <Button
                    danger
                    size="small"
                    icon={<CloseCircleOutlined />}
                    onClick={handleCancelWaiting}
                    className={style.thinkingTimeoutButton}
                    title="放弃等待"
                  >
                    放弃等待
                  </Button>
                </div>
              )}
            </div>
          )}
          {Object.values(conversationState.turns).map((turn: any) => {
            const steps = Object.values(turn.steps || {}) as any[];
            const pending = pendingClarifications(turn);
            // **老信封转出来的"空回合"不画** ✓✓：native 路由把终态**两条都发** ✓
            //（V1 事件给新 UI ✓、老信封帧给老 UI ✓）——而旧帧没有 `turnId` ✗
            //（`WSResponse` 没这个字段 ✓），前端把它转成 V1 事件时回合号只能是空串 ✓
            //（`conversationEvents.mjs` 的 `toConversationEvent` ✓），于是 reducer 里
            // 多出一个 `''` 回合 ✓，内容与真回合**完全重复** ✓（错误/提案/动作结果 ✓）。
            // 修前它被下面那条 gate 挡住 ✓；补进 answer/proposal/error 之后它**冒出来了** ✗✓
            //（实测：F15 的 `.last()` 落到空块上 → 看不到进度 ✓；F12 的停止按钮留在空块上 ✓；
            // F07 的终态断言被空块顶掉 ✓）。
            // 状态**照旧保留** ✓：`findActionResultFor` 按 proposalRef 全量找 ✓，
            // 删状态会让提案卡读不到执行结果 ✗——只是不渲染 ✓。
            if (!turn.id) return null;
            // **纯文本回合也要画** ✓✓：答案/提案/错误都渲染在**这个块里** ✓
            // （`assistant-final` / `ProposalCard` / `turn-error` ✓），而原来的 gate 只看
            // 工具进度与待答卡 ✗——一个"没有工具调用、直接回答"的回合（如打招呼/常识问答）
            // 整块不画 ✓✗，答案就只剩 REST 历史那一份 ✓：事件流那一份**永远不出现** ✓。
            // 补进三个渲染条件即可 ✓；**一个回合仍然只画一份** ✓（三者各自渲染一次 ✓，
            // 不去重、不改历史那条路 ✓）。
            if (
              steps.length === 0 &&
              pending.length === 0 &&
              !turn.answer &&
              !turn.proposal &&
              !turn.error
            ) return null;
            return (
              <div key={turn.id} data-turn-id={turn.id} style={{ padding: '4px 12px' }}>
                {steps.length > 0 ? (
                  <div data-testid="turn-progress">
                    {steps.map(step => (
                      <div key={step.itemId} data-testid="turn-progress-step" data-status={step.status}>
                        {step.label || step.tool}
                      </div>
                    ))}
                  </div>
                ) : null}
                <UnderstandingCard
                  understanding={turn.understanding}
                  onRefine={
                    turn.terminal ? undefined : () => handleSteerTurn(turn.id, '补充说明')
                  }
                />
                {/*
                  **提案卡** ✓✓（`proposal.preview` ✓）：事件早到了 ✓（网关算完预览 → 翻成合同形状 ✓），
                  缺的一直是"没人画它" ✗——与 `assistant-final` / `turn-error` 同一个病 ✓。
                  出站那一半**早就完整** ✓：确认/取消用的还是既有那条 `conversationAction` 帧 ✓
                  （`confirm_proposal` / `cancel_proposal` + `expectedSourceVersion` + `intent: 'explicit'` ✓）。
                */}
                {turn.proposal ? (
                  <ProposalCard
                    proposal={turn.proposal}
                    actionResult={findActionResultFor(
                      conversationStateRef.current,
                      turn.proposal.proposalRef,
                    )}
                    onDecide={(action) => handleProposalDecision(turn.proposal, action)}
                  />
                ) : null}
                {/*
                  **把 V1 终态的答案画出来** ✓✓（C4 真栈追出来的最后一格 ✓）：
                  reducer 早把它存进 `turn.answer.message` 了 ✓（`conversationSession.mjs:101` ✓），
                  而这个回合块只画了进度/停止/卡片 ✗ —— **答案没人渲染** ✓，所以界面上看不到 ✓。
                  数据在、形状对、就是差这一处渲染 ✓。
                */}
                {turn.terminal && turn.answer && turn.answer.message ? (
                  <div data-testid="assistant-final">{turn.answer.message}</div>
                ) : null}
                {/*
                  **可恢复错误也要画出来** ✓✓——与上面那条一模一样的病 ✗：
                  reducer 早把 `recoverable.error` 存进 `turn.error` 了 ✓
                  （`conversationSession.mjs:113` ✓），而这里从来不渲染它 ✗ →
                  模型输出坏掉的那一轮，用户那边**什么都没发生** ✗（实测：F15 整轮静默 ✓）。
                  文案用服务端给的 `message` ✓；它缺了才退回一句通用话 ✓（**不许空着** ✗）。
                */}
                {turn.error ? (
                  <div data-testid="turn-error">
                    {/* 两种键都要认 ✓✓：V1 事件带 `message` ✓，而**同一条失败**在老信封那条路上
                        带的是 `content` ✓——两条都会到（网关有意两条都发 ✓：老 UI 靠 reply ✓、
                        新 UI 靠 V1 ✓）。后到的老信封帧 `message` 可能是空串 ✗（失败结果里没有
                        `reply` ✓），**reducer 已拦**：空文案不覆盖已有文案 ✓
                        （`conversationSession.mjs` 的 `recoverable.error` 分支 ✓）。 */}
                    {turn.error.message || turn.error.content || '本轮没有完成，请稍后重试'}
                  </div>
                ) : null}
                {!turn.terminal ? (
                  <button
                    type="button"
                    data-testid="turn-stop"
                    onClick={() => handleInterruptTurn(turn.id)}
                  >
                    停止
                  </button>
                ) : null}
                {pending.map((card: any) => (
                  <ClarificationCard
                    key={card.requestId}
                    clarification={card}
                    onSubmit={(answer, meta) =>
                      handleClarificationAnswer(card.requestId, answer, meta.clientRequestId)
                    }
                  />
                ))}
              </div>
            );
          })}
          {/*
            **冷加载补一张"最后一条提案"的卡** ✓✗（理由见 props 里 `lastProposal` 那段 ✓）：
            回合块只在**事件到达**时才长出来 ✗，刷新之后一个都没有 ✓——所以这里按
            "回合里没画过这个 `proposalRef`" 判一次 ✓，补一张**只读**的卡 ✓（终态时按钮本来就收起 ✓）。
          */}
          {lastProposal?.proposalRef &&
          !Object.values(conversationState.turns || {}).some(
            (turn: any) =>
              String(turn?.proposal?.proposalRef || '') === String(lastProposal.proposalRef),
          ) ? (
            <ProposalCard
              proposal={{ proposalRef: lastProposal.proposalRef }}
              actionResult={{
                actionStatus: lastProposal.actionStatus,
                proposalRef: lastProposal.proposalRef,
              }}
              onDecide={() => undefined}
              disabled
            />
          ) : null}
          <div ref={bottomRef} />
        </Spin>
      </div>

      {shouldShowQuickReplies && (
        <div className={style.quickReplyBar}>
          {quickReplyList.map((action, idx) => (
            <div
              key={idx}
              className={style.quickReplyItem}
              onClick={() => {
                if (action.messageText) {
                  void handleSendPresetMessage(action.messageText);
                  return;
                }
                action.onClick?.();
              }}
            >
              <span className={style.quickReplyIcon}>{action.icon}</span>
              <span className={style.quickReplyLabel}>{action.label}</span>
            </div>
          ))}
        </div>
      )}
      <div className={style.sendMessage}>
        <Input
          // e2e 用的稳定钩子 ✓（Task C4 ✓）：文案会改 ✓，testid 不会 ✓。
          data-testid="chat-input"
          value={userInput}
          onChange={e => setUserInput(e.target.value)}
          placeholder="请输入您的问题或需求..."
          onKeyDown={handleKeyDown}
          suffix={
            <Button
              data-testid="chat-send"
              type="primary"
              shape="round"
              onClick={() => {
                handleSendMsg();
              }}
              disabled={!userInput}
            >
              发送
              <img src={SendPng.src} alt="发送" />
            </Button>
          }
        />
      </div>

      {wsMessageList.length > 0 && (
        <div className={style.notReadContainer} onClick={scrollToBottom}>
          <VerticalAlignBottomOutlined />
          有新消息
        </div>
      )}
    </div>
  );
});

export default MessageList;
