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
}

export interface UseWebSocketReturn {
  sendMessage: (message: WebSocketMessage | string) => void;
  disconnect: () => void;
  reconnect: () => void;
  isConnected: boolean;
  lastMessage: WebSocketMessage | string | null;
  reconnectCount: number;
}
