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
import { PlanningWorkspaceIntent } from '@/interface/api/volunteer';
import {
  getEntityPropertyAnalyzeApi,
  getMessageListApi,
  getFeedbackApi,
} from '@/service/apis/sessionDetail';
import style from './style.module.scss';
import { TextSegment } from '@/interface/api/sessionDetail';
import useAuthParams from '@/hooks/useAuthParams';
import { useWebSocket } from '@/hooks/useWebSocket';
import { WebSocketMessage } from '@/hooks/websocket';
import TypingAnimation from '@/components/generating/TypingAnimation';
import SendPng from '@/images/icons/send.png';
import { marked } from 'marked';
import { createFetchQueue } from './fetchQueue.mjs';

marked.use({ gfm: true, breaks: true });

const renderMarkdown = (content: string) => marked.parse(content) as string;

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
  targetView?: PlanningWorkspaceIntent['targetView'];
  volunteerIds?: string[];
  refresh?: boolean;
  candidateFilters?: PlanningWorkspaceIntent['candidateFilters'];
  kind?: 'intent_change' | 'plan_mutation';
  actionFamily?: string;
  summary?: string;
  pendingId?: string;
  status?: 'active' | 'applied' | 'cancelled' | 'replaced' | 'expired';
  confirmText?: string;
  cancelText?: string;
}

const isIntentConfirmCard = (contentObj?: IIntentCardContent | null) =>
  contentObj?.type === 'planEditSelectPopup' ||
  contentObj?.type === 'intentDetectSelectPopup' ||
  contentObj?.type === 'intentConfirmPopup';

const isInterestAnalysisCard = (contentObj?: IIntentCardContent | null) =>
  contentObj?.type === 'interestAnalysisPopup';

const isPendingConfirmationCard = (contentObj?: IIntentCardContent | null) =>
  contentObj?.type === 'pendingConfirmationCard';

const isIntentAnalysisCard = (contentObj?: IIntentCardContent | null) =>
  isIntentConfirmCard(contentObj) || isInterestAnalysisCard(contentObj);

const supportedWorkspaceTargetViews = new Set(['candidate', 'ordered']);

const normalizeWorkspaceTargetView = (
  targetView: unknown
): PlanningWorkspaceIntent['targetView'] | null => {
  if (typeof targetView !== 'string' || !supportedWorkspaceTargetViews.has(targetView)) {
    return null;
  }
  return targetView as PlanningWorkspaceIntent['targetView'];
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
  if (!targetView) {
    return null;
  }
  return {
    targetTab: 'volunteer',
    targetView,
    volunteerIds: Array.isArray(contentObj.volunteerIds) ? contentObj.volunteerIds : [],
    refresh: Boolean(contentObj.refresh),
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

const MessageList = forwardRef<IMessageParams, IMessageListProps>((props, ref) => {
  const {
    routerParams,
    scrollEleIndex,
    setEntityCardList,
    quickReplyActions,
    alwaysShowQuickReplyActions,
    onWorkspaceIntent,
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
          const currentPage = queuedPage ?? pageRef.current;

          setIsLoading(true);

          const container = messageContainerRef.current;
          // 记录当前滚动位置和高度
          const prevScrollHeight = container?.scrollHeight || 0;
          const prevScrollTop = container?.scrollTop || 0;
          try {
            const { data, code } = await getMessageListApi(routerParams.tenantId, {
              chatSessionId: +routerParams.chatSessionId,
              orderBy: [
                // 排序规则
                { isAsc: false, orderBy: 'id' },
              ],
              page: currentPage,
              pageSize: 10,
            });
            if (code === 0 && data) {
              const reverseList = data.records
                .filter(record => !isStructuredIntentSelectEcho(record))
                .reverse();
              const dealReverseList = reverseList.map(record => ({
                ...record,
                contentSegments: record.contentSegments,
              }));
              setMessageList(prevList => {
                const merged = [...dealReverseList, ...prevList]
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
              message.error('获取消息列表失败');
            }
          } finally {
            setIsLoading(false);
          }
        });
      }

      return fetchQueueRef.current.enqueue(tempPage);
    },
    [autoScroll, routerParams.chatSessionId, routerParams.tenantId]
  );

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
  // const websocketUrl = `/gaotu-assistant-agent/plus/chat/${tenantId}/bot/${botId}/do`;
  const wsBase =
    process.env.NEXT_PUBLIC_AGENT_WS_BASE_OVERRIDE || process.env.NEXT_PUBLIC_AGENT_WS_BASE || '';
  const websocketUrl = `${wsBase}/gaotu-assistant-agent/plus/chat/${tenantId}/bot/${botId}/do`;

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

  const { sendMessage, disconnect, reconnect, isConnected } = useWebSocket(websocketUrl, {
    onMessage(data, event) {
      if (typeof data === 'object' && data !== null && 'type' in data) {
        const wsData = data as IThinkingMessage;
        if (wsData.type === 'thinking') {
          appendThinkingHint(wsData.content);
          return;
        }
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
      fetchMessageList();
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
    fetchMessageList();

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
    if (userInput) {
      sendMessage?.({
        sessionId: routerParams.chatSessionId,
        userId: routerParams.userId || '',
        content: userInput,
        inputType: 'text',
      });
      setUserInput('');
      await fetchMessageList();

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
    sendMessage?.({
      sessionId: routerParams.chatSessionId,
      userId: routerParams.userId || '',
      content: preset,
      inputType: 'text',
    });
    setUserInput('');
    await fetchMessageList();

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

      // 如果是意向确认卡片且 selected 为空，则不刷新右侧
      if (isIntentConfirmCard(contentObj) && selected.length === 0) {
        return;
      }

      setFetchFlag(prev => prev + 1);
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

  const markPendingConfirmationCardHandled = (
    messageId: number,
    status: 'applied' | 'cancelled'
  ) => {
    setMessageList(prevList =>
      prevList.map(item => {
        if (item.id !== messageId || item.contentType !== 'CARD') {
          return item;
        }
        const contentObj = parseCardContent(item.content);
        if (!isPendingConfirmationCard(contentObj)) {
          return item;
        }
        return {
          ...item,
          content: JSON.stringify({
            ...contentObj,
            clickable: false,
            clicked: status === 'applied',
            status,
          }),
        };
      })
    );
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

  const renderAnalysisSection = (title: string, items?: string[]) => {
    if (!Array.isArray(items) || items.length === 0) {
      return null;
    }
    return (
      <div className={style.analysisTextSection}>
        <div className={style.analysisTextSectionTitle}>{title}</div>
        <div className={style.analysisTextList}>
          {items.map((item, index) => (
            <div key={`${title}-${index}`} className={style.analysisTextListItem}>
              <span className={style.analysisTextBullet}>-</span>
              <span className={style.analysisTextListItemContent}>{item}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderIntentAnalysisBlock = (
    analysis?: IIntentAnalysisContent,
    impactTitle?: string
  ) => {
    const hasAnalysis =
      analysis &&
      [
        analysis.currentPlanFit,
        analysis.currentPlanConflict,
        analysis.candidateOpportunity,
        analysis.nextActionHints,
      ].some(items => Array.isArray(items) && items.length > 0);

    if (!hasAnalysis) {
      return null;
    }

    return (
      <div className={style.analysisTextBlock}>
        <div className={style.analysisTextTitle}>{impactTitle || '方案关联分析'}</div>
        {analysis?.summaryTitle ? (
          <div className={style.analysisTextSummary}>{analysis.summaryTitle}</div>
        ) : null}
        {renderAnalysisSection('现在比较贴近的部分', analysis?.currentPlanFit)}
        {renderAnalysisSection('现在需要留意的部分', analysis?.currentPlanConflict)}
        {renderAnalysisSection('还可以再看看的机会', analysis?.candidateOpportunity)}
        {renderAnalysisSection('下一步建议', analysis?.nextActionHints)}
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
      await fetchMessageList();
    } catch (error) {
      resetAnswerLoading();
      console.error('兴趣分析动作发送失败', error);
    }
  };

  const handleWorkspaceCardClick = (contentObj: IIntentCardContent) => {
    const targetView = normalizeWorkspaceTargetView(contentObj.targetView);
    if (!targetView) {
      return;
    }
    onWorkspaceIntent?.({
      targetTab: 'volunteer',
      targetView,
      volunteerIds: contentObj.volunteerIds || [],
      refresh: contentObj.refresh,
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
      });
      markPendingConfirmationCardHandled(msg.id, action === 'confirm' ? 'applied' : 'cancelled');
      if (action === 'confirm') {
        setFetchFlag(prev => prev + 1);
      }
    } catch (error) {
      resetAnswerLoading();
      console.error('待确认卡片操作失败', error);
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

  const displayMessageList = messageList.filter(
    (record, index, records) => !isLegacyAutoPlanPrompt(record, index, records)
  );
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
                                    ['applied', 'cancelled', 'replaced', 'expired'].includes(
                                      effectiveContentObj?.status || ''
                                    );
                                  let statusText = '';
                                  if (effectiveContentObj?.status === 'applied' || effectiveContentObj?.clicked) {
                                    statusText =
                                      effectiveContentObj?.kind === 'intent_change' ? '已采纳' : '已确认';
                                  } else if (effectiveContentObj?.status === 'cancelled') {
                                    statusText =
                                      effectiveContentObj?.kind === 'intent_change' ? '未采纳' : '已取消';
                                  } else if (effectiveContentObj?.status === 'replaced') {
                                    statusText = '已被新的确认卡替代';
                                  } else if (effectiveContentObj?.status === 'expired') {
                                    statusText = '已失效';
                                  }
                                  return (
                                    <div className={style.pendingConfirmationCard}>
                                      <div className={style.pendingConfirmationHeader}>
                                        <span className={style.pendingConfirmationBadge}>待确认</span>
                                        <div className={style.pendingConfirmationTitle}>
                                          {effectiveContentObj.title || '请确认本次方案调整'}
                                        </div>
                                      </div>
                                      {(effectiveContentObj.summary || effectiveContentObj.content) ? (
                                        <div className={style.pendingConfirmationContent}>
                                          {effectiveContentObj.summary || effectiveContentObj.content}
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
                                    ) : isInterestAnalysisCard(contentObj) &&
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
              <div
                className={style.thinkingContent}
                style={{ paddingRight: isTimeout ? '120px' : '0' }}
              >
                <div className={style.thinkingLabel}>正在分析</div>
                <div className={style.thinkingCurrentHint}>
                  <TypingAnimation text={thinkingHints[thinkingHints.length - 1] || '思考中'} />
                </div>
              </div>
              {isTimeout && (
                <Button
                  type="primary"
                  danger
                  size="small"
                  icon={<CloseCircleOutlined />}
                  onClick={handleCancelWaiting}
                  style={{
                    position: 'absolute',
                    right: '40px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    height: '36px',
                    borderRadius: '18px',
                    fontWeight: 500,
                    boxShadow: '0 2px 8px rgba(255, 68, 61, 0.3)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '0 16px',
                  }}
                  title="放弃等待"
                >
                  放弃等待
                </Button>
              )}
            </div>
          )}
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
          value={userInput}
          onChange={e => setUserInput(e.target.value)}
          placeholder="请输入您的问题或需求..."
          onKeyDown={handleKeyDown}
          suffix={
            <Button
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
