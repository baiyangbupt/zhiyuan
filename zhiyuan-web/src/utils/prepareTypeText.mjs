// 志愿模式码归一（纯逻辑，node:test 直接测）。
//
// 为什么单独放一个 .mjs：这段判定原先在两个组件里各抄了一份
// （`pages/sessionDetailV2/index.tsx` 与 `pageComponents/sessionDetailV2/WorkspacePanel/index.tsx`），
// 而它的判据是"先看整串里有没有 `智能填报` 字样"——但后端 desc 字段自身混用：
// **PREDICT 会话的 desc 大量就是"智能填报"**（2026-10-08 核查实锤：demo 日志里
// PREDICT/智能填报 170 次、PREDICT/模拟填报 28 次、VOLUNTEER/智能填报 18 次）。
// 于是真 PREDICT 会话被误判成 VOLUNTEER：弹"2026年招生计划数据已更新"、
// planYear 取 2026，而同一会话的后端摘要却写着"模拟填报使用2025年的志愿数据"
// —— 同页自相矛盾（2026-10-08 核查实锤）。
//
// 口径（2026-10-08）：**code 优先；desc 只作兜底，且只认各自的本义词**——
//   PREDICT ↔ 模拟填报；VOLUNTEER ↔ 智能填报。
// desc 混用时不再靠"字样先后"猜模式（旧实现正是错在把 `智能填报` 判给了 VOLUNTEER）。
export function normalizePrepareTypeCode(code, desc) {
  const codeText = `${code || ''}`.toUpperCase();
  if (codeText.includes('PREDICT')) {
    return 'PREDICT';
  }
  if (codeText.includes('VOLUNTEER')) {
    return 'VOLUNTEER';
  }
  const descText = `${desc || ''}`;
  if (descText.includes('模拟填报')) {
    return 'PREDICT';
  }
  if (descText.includes('智能填报')) {
    return 'VOLUNTEER';
  }
  return '';
}

export const isPredictPrepareType = (code, desc) =>
  normalizePrepareTypeCode(code, desc) === 'PREDICT';

export const isVolunteerPrepareType = (code, desc) =>
  normalizePrepareTypeCode(code, desc) === 'VOLUNTEER';
