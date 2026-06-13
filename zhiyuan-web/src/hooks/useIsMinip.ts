import { useState, useEffect } from 'react';
import { getUa, getValueFromUrlBykey } from '@/utils/tool';

/**
 * 判断当前是否为小程序端。
 * PC 端可能残留历史 source=minip storage，不能只靠持久化标识判断，否则会误跳移动端会话抽屉。
 */
export const useIsMinip = (): boolean => {
  const [isMinip, setIsMinip] = useState(false);

  useEffect(() => {
    const fromUrl = getValueFromUrlBykey('source') === 'minip';
    setIsMinip(fromUrl || getUa().isWechatMP);
  }, []);

  return isMinip;
};
