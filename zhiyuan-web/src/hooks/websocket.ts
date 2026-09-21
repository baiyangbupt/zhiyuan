// types/websocket.ts
export interface WebSocketMessage {
  sessionId: string;
  userId: string;
  content: any;
  inputType: string;
  [key: string]: any;
}

export interface WebSocketOptions {
  onOpen?: (event: Event) => void;
  onMessage?: (data: WebSocketMessage | string, event: MessageEvent) => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (error: Event) => void;
  autoReconnect?: boolean; // 是否启用自动重连（默认 true）
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  /**
   * 每次连接尝试前调用，返回要附加到 URL 上的查询参数。
   *
   * 之所以是"每次连接"而不是"每次挂载"：票据是一次性且短命的，
   * 重连时必须换一张新的。
   */
  authenticate?: () => Promise<Record<string, string>>;
}

export interface UseWebSocketReturn {
  sendMessage: (message: WebSocketMessage | string) => void;
  disconnect: () => void;
  reconnect: () => void;
  isConnected: boolean;
  lastMessage: WebSocketMessage | string | null;
  reconnectCount: number;
}
