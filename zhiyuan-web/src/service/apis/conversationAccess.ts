import request from '@/service/index';
import { IWsTicketParams, IWsTicketRes } from '@/interface/api/conversationAccess';

/**
 * 换取一张 WebSocket 票据。
 *
 * 票据是一次性的、60 秒有效，所以**每次连接都要重新取**——
 * 重连时复用旧票会被服务端拒绝（它已经用掉了）。
 */
export const fetchWsTicketApi = (tenantId: string, data: IWsTicketParams) =>
  request<IWsTicketParams, IWsTicketRes>({
    url: `/gaotu-assistant-bot/chat/${tenantId}/conversation/ws-ticket`,
    method: 'post',
    data,
  });
