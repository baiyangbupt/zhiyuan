import { ISessionListResItem } from '@/interface/api/assistant';
import { getSessionList } from '@/service/apis/sessionDetail';

const hasSessionIdentity = (session?: Partial<ISessionListResItem> | null): session is ISessionListResItem =>
  Boolean(session?.id);

export const resolveCreatedSession = async (
  tenantId: string,
  botId: string,
  session?: Partial<ISessionListResItem> | null
): Promise<ISessionListResItem | null> => {
  if (hasSessionIdentity(session)) {
    return session;
  }

  const { code, data } = await getSessionList(tenantId, {
    botId,
    statusList: [],
    orderBy: [{ isAsc: false, orderBy: 'id' }],
    searchWord: '',
    page: 1,
    pageSize: 1,
  });

  if (code !== 0) {
    return null;
  }

  return data?.records?.[0] || null;
};
