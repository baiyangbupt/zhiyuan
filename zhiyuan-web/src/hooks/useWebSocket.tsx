// hooks/useWebSocket.ts
import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { WebSocketMessage, WebSocketOptions, UseWebSocketReturn } from './websocket';

export const useWebSocket = (url: string, options: WebSocketOptions = {}): UseWebSocketReturn => {
  const {
    onOpen,
    onMessage,
    onClose,
    onError,
    autoReconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = Number.POSITIVE_INFINITY,
    authenticate,
    tenantId,
    botId,
  } = options;

  // **V3 路由（`/ws/chat` ✓）要求消息里带 tenant** ✓✓：老路由把它写在路径里 ✓
  //（`/gaotu-assistant-agent/plus/chat/{tenant}/bot/{bot}/do` ✓），而 V3 的入口从
  // `msg.tenant_id` 读 ✓（`app/server.py:560` ✓），缺了就回
  // `缺少 tenantId，无法执行本轮对话。` ✗（2026-09-26 真栈实测 ✓）。
  // 在这里**一处**补齐 ✓：所有出站对象都经过它 ✓，不必去每个调用点各加一遍 ✗。
  // 另外补 `type` ✓✓：V3 的 `WSMessage` 把它列为**必填**的字面量 ✓（`app/schemas/ws.py:22` ✓，
  // 取值 `chat`/`pendingConfirmation`/… ✓），而老形状**没有这个字段** ✗（它靠"有 content"推断是 chat ✓）。
  // 缺了它 V3 直接判 `消息格式错误` ✗（实测 ✓）。默认给 `chat` ✓——页面发起的这些出站里，
  // 带 control 语义的那几种（澄清/中断/改口 ✓）走的是 `conversationProtocol.mjs` 的**显式**构造 ✓，
  // 那些对象里已有 `type` ✓，会被这里的展开**保留** ✓✓（`...message` 在后 ✓）。
  // **类型也要对** ✓✓：`tenantId`/`botId` 在页面上是**数字** ✓，而 V3 的模型要求 string ✗——
  // 传数字会被判 `Input should be a valid string` ✓（**本地复现**得出 ✓：把真实载荷直接喂给
  // `WSMessage.model_validate(...)` ✓，一行就说出原因 ✓✓，比翻日志快得多 ✓——因为服务端那条
  // 失败分支是**裸 except** ✗，什么都不记 ✓）。
  const withScope = (message: WebSocketMessage | string) =>
    typeof message === 'string'
      ? message
      : {
          tenantId: tenantId === undefined ? undefined : String(tenantId),
          botId: botId === undefined ? undefined : String(botId),
          type: 'chat',
          ...message,
        };

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const pendingMessagesRef = useRef<Array<WebSocketMessage | string>>([]);
  // 队列必须有上限，且**换 URL 时清空**：
  // 上限缺失时，一次长时间断线会把用户所有离线输入攒在内存里；
  // 不清空则会把上一个会话的消息发进新会话——用户在新页面里看到自己的话
  // 被发到了别处，而且没有任何提示。
  const MAX_PENDING_MESSAGES = 20;

  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | string | null>(null);
  const [reconnectCount, setReconnectCount] = useState<number>(0);

  // 使用 useMemo 来记忆选项回调函数，避免不必要的重新创建
  const callbacks = useMemo(
    () => ({
      onOpen,
      onMessage,
      onClose,
      onError,
      authenticate,
    }),
    [onOpen, onMessage, onClose, onError, authenticate]
  );

  const connect = useCallback(async () => {
    // 只在客户端执行
    if (typeof window === 'undefined') {
      return;
    }

    // 如果组件已卸载，不再尝试连接
    if (!isMountedRef.current) {
      return;
    }

    // 如果已经连接或正在连接，不再重复连接
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      console.log('WebSocket already connected or connecting');
      return;
    }

    // 检查重连次数限制
    if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
      console.warn(`Max reconnect attempts (${maxReconnectAttempts}) reached`);
      return;
    }

    try {
      console.log('🔄 建立对话通道连接（地址不入日志）');
      // 票据是**一次性且短命**的：每次连接尝试都要重新取。
      // 复用上一张票会在重连时被服务端拒掉（它已经用掉了），
      // 而那种失败看起来像"网络问题"，很难查。
      let connectUrl = url;
      if (callbacks.authenticate) {
        let params: Record<string, string>;
        try {
          params = await callbacks.authenticate();
        } catch (authError) {
          // 取不到票就不连：连上去也会被拒，还会白白消耗一次重连计数。
          console.warn('取票失败，本次不连接');
          return;
        }
        const query = new URLSearchParams(params).toString();
        if (query) {
          connectUrl = `${url}${url.includes('?') ? '&' : '?'}${query}`;
        }
      }
      const socket = new WebSocket(connectUrl);
      wsRef.current = socket;

      socket.onopen = (event: Event) => {
        if (!isMountedRef.current) return;

        console.log('✅ WebSocket connected successfully');
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        setReconnectCount(0);
        if (pendingMessagesRef.current.length > 0) {
          const pendingMessages = [...pendingMessagesRef.current];
          pendingMessagesRef.current = [];
          pendingMessages.forEach(message => {
            try {
              socket.send(JSON.stringify(withScope(message)));
              console.log('📤 Queued message sent successfully');
            } catch (error) {
              console.error('❌ Failed to send queued message:', error);
              pendingMessagesRef.current.unshift(message);
            }
          });
        }
        callbacks.onOpen?.(event);
      };

      socket.onmessage = (event: MessageEvent) => {
        if (!isMountedRef.current) return;

        try {
          const data: WebSocketMessage = JSON.parse(event.data);
          setLastMessage(data);
          callbacks.onMessage?.(data, event);
        } catch (error) {
          setLastMessage(event.data);
          callbacks.onMessage?.(event.data, event);
        }
      };

      socket.onclose = (event: CloseEvent) => {
        if (!isMountedRef.current) return;

        console.log('🔌 WebSocket disconnected');
        setIsConnected(false);
        callbacks.onClose?.(event);

        // 自动重连逻辑
        if (autoReconnect && !reconnectTimerRef.current && isMountedRef.current) {
          reconnectAttemptsRef.current += 1;
          setReconnectCount(prev => prev + 1);

          reconnectTimerRef.current = setTimeout(() => {
            reconnectTimerRef.current = null;
            if (reconnectAttemptsRef.current <= maxReconnectAttempts && isMountedRef.current) {
              console.log(
                `Attempting reconnect (${reconnectAttemptsRef.current}/${maxReconnectAttempts})`
              );
              void connect();
            }
          }, reconnectInterval);
        }
      };

      socket.onerror = (error: Event) => {
        if (!isMountedRef.current) return;

        console.error('❌ WebSocket error');
        callbacks.onError?.(error);
      };
    } catch (error) {
      console.error('❌ Failed to create WebSocket:', error);
    }
  }, [url, autoReconnect, reconnectInterval, maxReconnectAttempts, callbacks]);

  const sendMessage = useCallback(
    (message: WebSocketMessage | string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify(withScope(message)));
          console.log('📤 Message sent successfully');
        } catch (error) {
          console.error('❌ Failed to send message:', error);
        }
      } else {
        console.warn('⚠️ WebSocket is not connected');
        pendingMessagesRef.current.push(message);
        if (pendingMessagesRef.current.length > MAX_PENDING_MESSAGES) {
          // 丢最旧的：新输入更可能还是用户想要的那条。
          pendingMessagesRef.current.splice(
            0,
            pendingMessagesRef.current.length - MAX_PENDING_MESSAGES,
          );
          console.warn('待发队列已满，丢弃了最旧的待发消息');
        }
        if (!isConnected) {
          console.log('Attempting to reconnect...');
          void connect();
        }
      }
    },
    [isConnected, connect]
  );

  const disconnect = useCallback(() => {
    console.log('🛑 Disconnecting WebSocket');

    // 清除重连定时器
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    // 关闭 WebSocket 连接
    if (wsRef.current) {
      // 先移除事件监听器，避免在关闭过程中触发重连
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;

      // 检查当前状态，避免在已经关闭或正在关闭时再次调用 close
      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close();
      }
      wsRef.current = null;
    }

    setIsConnected(false);
    reconnectAttemptsRef.current = 0;
    setReconnectCount(0);
  }, []);

  // 手动重连方法
  const reconnect = useCallback(() => {
    console.log('🔄 Manual reconnect requested');
    // 先断开连接
    disconnect();
    // 重置重连计数，允许重新连接
    reconnectAttemptsRef.current = 0;
    // 延迟一下再连接，确保断开完成
    setTimeout(() => {
      if (isMountedRef.current) {
        void connect();
      }
    }, 100);
  }, [disconnect, connect]);

  useEffect(() => {
    isMountedRef.current = true;

    // 换了 URL 就是换了会话/环境：上一条会话没发出去的消息**不能**带过去。
    pendingMessagesRef.current = [];
    reconnectAttemptsRef.current = 0;

    // 只在客户端执行连接；url 变化时需要重连到新的会话/环境地址。
    if (typeof window !== 'undefined') {
      console.log('🏗️ 连接对话通道（地址不入日志）');
      void connect();
    }

    return () => {
      console.log('🧹 WebSocket url cleanup, disconnecting current WebSocket');
      disconnect();
    };
  }, [url]);

  useEffect(
    () => () => {
      isMountedRef.current = false;
    },
    []
  );

  // 调试信息只留状态，不留地址：`wsRef.current.url` 里带着查询串上的票据，
  // 它落到控制台就等于落到了任何能看到控制台的人手里。
  useEffect(() => {
    console.log('WebSocket ref state:', {
      readyState: wsRef.current?.readyState,
    });
  }, [isConnected, reconnectCount]);

  return {
    sendMessage,
    disconnect,
    reconnect,
    isConnected,
    lastMessage,
    reconnectCount,
  };
};
