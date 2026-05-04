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
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const pendingMessagesRef = useRef<Array<WebSocketMessage | string>>([]);

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
    }),
    [onOpen, onMessage, onClose, onError]
  );

  const connect = useCallback(() => {
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
      console.log('🔄 Creating new WebSocket connection to:', url);
      const socket = new WebSocket(url);
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
              const data = typeof message === 'string' ? message : JSON.stringify(message);
              socket.send(data);
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
              connect();
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
          const data = typeof message === 'string' ? message : JSON.stringify(message);
          wsRef.current.send(data);
          console.log('📤 Message sent successfully');
        } catch (error) {
          console.error('❌ Failed to send message:', error);
        }
      } else {
        console.warn('⚠️ WebSocket is not connected');
        pendingMessagesRef.current.push(message);
        if (!isConnected) {
          console.log('Attempting to reconnect...');
          connect();
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
        connect();
      }
    }, 100);
  }, [disconnect, connect]);

  useEffect(() => {
    isMountedRef.current = true;

    // 只在客户端执行连接
    if (typeof window !== 'undefined') {
      console.log('🏗️ Component mounted, connecting WebSocket');
      connect();
    }

    // 清理函数 - 只在组件卸载时执行
    return () => {
      console.log('🧹 Component unmounting, cleaning up WebSocket');
      isMountedRef.current = false;
      disconnect();
    };
  }, []); // 空依赖数组，只在挂载和卸载时执行

  // 添加调试信息
  useEffect(() => {
    console.log('WebSocket ref state:', {
      current: wsRef.current,
      readyState: wsRef.current?.readyState,
      url: wsRef.current?.url,
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
