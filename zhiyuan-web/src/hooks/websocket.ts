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
  /**
   * V3 路由（`/ws/chat` ✓）要求**消息里带 tenant** ✓✓——老路由把它写在路径里 ✓
   *（`/gaotu-assistant-agent/plus/chat/{tenant}/bot/{bot}/do` ✓），而 V3 的入口从
   * `msg.tenant_id` 读 ✓（`app/server.py:560` ✓），缺了就回
   * `缺少 tenantId，无法执行本轮对话。` ✗（2026-09-26 真栈实测 ✓）。
   */
  tenantId?: string;
  botId?: string;
}

export interface UseWebSocketReturn {
  sendMessage: (message: WebSocketMessage | string) => void;
  disconnect: () => void;
  reconnect: () => void;
  isConnected: boolean;
  lastMessage: WebSocketMessage | string | null;
  reconnectCount: number;
}
