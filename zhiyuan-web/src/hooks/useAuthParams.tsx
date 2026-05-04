import { useEffect } from 'react';
import { getStorage, EStorageKey, getValueFromUrlBykey } from '@/utils/tool';
import { navigateTo } from '@/utils/router';

interface UseAuthParamsReturn {
    botId: string;
    tenantId: string;
}

const useAuthParams = (): UseAuthParamsReturn => {
    // 直接同步获取参数
    const storedBotId = getStorage(EStorageKey.BOT_ID) as string;
    const storedTenantId = getStorage(EStorageKey.TENANT_ID) as string;
    
    // 优先从localStorage获取，如果没有则从URL获取（兼容旧链接）
    const botId = storedBotId || getValueFromUrlBykey('botId') || '1';
    const tenantId = storedTenantId || getValueFromUrlBykey('tenantId') || '1';
    
    // 使用useEffect在客户端执行导航逻辑，避免SSR问题
    useEffect(() => {
        // 如果localStorage中没有值且URL中也没有值，跳转到登录页
        if (!storedBotId && !storedTenantId && !getValueFromUrlBykey('botId') && !getValueFromUrlBykey('tenantId')) {
            navigateTo('/login');
        }
    }, [storedBotId, storedTenantId]);

    return { botId, tenantId };
};

export default useAuthParams; 