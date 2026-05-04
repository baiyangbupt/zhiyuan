import { useState, useEffect } from 'react';

/**
 * 检测视口宽度是否 <= 指定断点
 */
export const useMediaQuery = (maxWidth: number): boolean => {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
    return window.matchMedia(`(max-width: ${maxWidth}px)`).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      setMatches(false);
      return undefined;
    }
    const media = window.matchMedia(`(max-width: ${maxWidth}px)`);
    setMatches(media.matches);
    const handler = (e: MediaQueryListEvent | MediaQueryList) => setMatches(e.matches);

    // 兼容低版本 WebView / Safari，仅支持 addListener/removeListener。
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', handler as EventListener);
      return () => media.removeEventListener('change', handler as EventListener);
    }

    if (typeof media.addListener === 'function') {
      media.addListener(handler);
      return () => media.removeListener(handler);
    }

    return undefined;
  }, [maxWidth]);

  return matches;
};
