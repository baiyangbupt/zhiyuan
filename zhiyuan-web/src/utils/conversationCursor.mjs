/**
 * 断线续传的**游标** = `(代际, 序号)` ✓✓——它同时是两件事：
 *   · 客户端去重的依据 ✓（reducer 按同一对键判"重复 / 缺口" ✓）；
 *   · 服务端补发的入参 ✓（`event_store.replay(key, epoch, after=sequence)` ✓，
 *     连上去时挂在 URL 上：`?epoch=…&since=…` ✓）。
 *
 * 三条口径，每条都对应一个踩过的坑：
 *
 * 1. **老的"本地序号"不能当游标** ✗：老信封（`{type:'reply'}` 那类）没有真编号，
 *    转换时只能就地编一个本地序号 ✗——它在本次连接内可用、跨重连毫无意义 ✓。
 *    转换产物带的代际是常量 `local` ✓，这里把它挡掉 ✓（A6 报告原话：
 *    `localSequence: true` 就是"此序号不可用于恢复"的标记 ✓）。
 * 2. **不落盘** ✗✓：游标**只**在页面还活着时有效 ✓。刷新会清掉 reducer 状态 ✓，
 *    但存储清不掉 ✗——带着"我看过到 N"的游标重连，服务端只会补尾巴 ✗，
 *    而页面其实一点状态都没有 ✗ → 在飞回合的前半段**永远回不来** ✓
 *    （少了它，F10 那条用例要的"刷新后整回合恢复"就成立不了 ✓）。
 * 3. 拿不出合法游标时**返回 null** ✓（含义是"我没有游标" ✓）——**不编一个假的** ✗：
 *    编了服务端会照着它补，补出来的东西和客户端状态对不上 ✓。
 */

/** 老信封转换产物用的常量代际：它代表"这不是真编号" ✗。 */
export const LOCAL_EPOCH = 'local';

/**
 * 会话状态 → 游标；拿不出合法游标就是 `null`。
 *
 * 只认"真代际 + 正整数序号"：序号从 1 起（服务端的编号也是从 1 起 ✓），
 * 0 表示"还没读到任何编号事件" ✓——那时也没什么可续的 ✓。
 */
export function cursorFromState(state) {
  const epoch = state?.streamEpoch;
  const sequence = state?.lastSequence;
  if (typeof epoch !== 'string' || !epoch || epoch === LOCAL_EPOCH) return null;
  if (typeof sequence !== 'number' || !Number.isInteger(sequence) || sequence < 1) return null;
  return { epoch, sequence };
}
