// 心跳看门狗：判断"这条连接还回不回 pong"。
//
// 2026-10-06 的事故（确认执行期间连接静默死亡、页面既不重连也不报错、F5 才恢复）里，
// 检测判据写在组件里、量的是"距上次 ping 的时长"——而每个心跳 tick 都会把
// "上次 ping 的时间"重写成 now，于是它**永远小于 tick 间隔（5s）**，
// `> 30s 判死` 那一支一次都不可能触发：连接死了也没有任何人发起重连。
//
// 可靠的锚点只有一个：**最近一次 pong**。ping 只负责给对方一个回 pong 的机会，
// 它本身不是"还活着"的证据，不能进静默窗口。把判据抽成纯函数（node:test 直接测，
// 见 heartbeatWatchdog.test.mjs），组件那一侧只负责调用与重连。
//
// 为什么必须是它来兜底：TCP 半开（对端进程死了/NAT 掉了映射，但没人发 FIN）
// 不会给 `onclose`/`onerror`，浏览器直到自己把 TCP 重传耗尽前都认为连接是 OPEN 的
// ——心跳超时是唯一能在 30s 量级上发现"假死"的探针。

export const HEARTBEAT_TIMEOUT_MS = 30000;

/**
 * **后台标签页的节流**（2026-10-07 独立审查 M4 ✓）：浏览器会把隐藏标签的定时器
 * 节流（`setInterval(…, 5s)` 实测可拉成分钟级 ✓）甚至整页冻结 ✓——隐藏期里
 * ping 与 pong **都没有机会跑** ✗，而"距上次 pong 的时长"照走 ✓ → 回到前台/解冻后的
 * 第一个 tick 就会拿一整段"没人有机会回 pong"的时长去判死 ✗ → 一条**好好**的连接
 * 被误杀重连 ✓（在飞的确认回合还被本地收尾 ✗）。两条纪律：
 *   ① **隐藏期跳过判死** ✓——那时的静默不是连接死亡的证据 ✓；
 *   ② **回到前台复位窗口** ✓——否则隐藏期的时长会在下一个 tick 直接超时 ✓。
 * 判据是纯函数（node:test 直接测 ✓，见 heartbeatWatchdog.test.mjs ✓）；
 * 参数默认给"前台" ✓（拿不到 `document` 的老环境/SSR 退回原行为 ✓，不凭空停掉判死 ✗）。
 */
export function shouldSkipSilenceCheck(visibilityState) {
  return visibilityState === 'hidden';
}

/** 回到前台要复位静默窗口（见上）；隐藏/未知状态不动。 */
export function shouldRearmWatchdog(visibilityState) {
  return visibilityState === 'visible';
}

export function createHeartbeatWatchdog({ timeoutMs = HEARTBEAT_TIMEOUT_MS } = {}) {
  let armed = false;
  let lastPongAt = 0;

  return {
    /** 连接（重）建立时调用：静默窗口从这一刻起算（允许"还没收到第一口 pong"的新连接）。 */
    reset(now = Date.now()) {
      armed = true;
      lastPongAt = now;
    },
    /** 收到 pong：活着，静默窗口清零。 */
    touchPong(now = Date.now()) {
      if (armed) lastPongAt = now;
    },
    /** 停止盯防（连接已断/组件卸载）：别拿旧时间戳去判死。 */
    stop() {
      armed = false;
      lastPongAt = 0;
    },
    /** 距离最近一次 pong 静默了多久（毫秒）；没在盯防时为 0。 */
    silenceFor(now = Date.now()) {
      return armed ? Math.max(0, now - lastPongAt) : 0;
    },
    /** 静默达到超时 ⇒ 这条连接已被判死。 */
    isSilent(now = Date.now()) {
      return armed && now - lastPongAt >= timeoutMs;
    },
  };
}
