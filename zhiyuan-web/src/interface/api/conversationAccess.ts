export interface IWsTicketParams {
  sessionId: string;
  botId: string;
}

export interface IWsTicketRes {
  ticket: string;
  expiresInSeconds: number;
}
