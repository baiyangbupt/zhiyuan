/**
 * 「直接进对话」：建一个**空会话**，信息留给对话采集。
 *
 * 这是评估用的旁路，不是产品流程。要恢复「请完善学生的高考信息」抽屉与
 * `/customerDetail` 分步表单，把 `SKIP_PREFILL_FORM` 改回 false 即可。
 *
 * 为什么建的是空会话而不是"填一份默认值"：省份/批次/选科/成绩本来就是
 * **对话要达到目标时要采集的信息**。前端塞默认值的话，会话里就坐着一条假信息，
 * 模型会把它当成已知条件，反而不会再问缺什么——恰好把要观察的行为盖掉。
 * 空会话由后端 `CreateSessionReq.draft` 支持：跳过五项硬校验与全量取数，
 * 仅保留权益校验。
 */
export const SKIP_PREFILL_FORM = true;

export const buildDirectSessionParams = (botId: string | number) => ({
  botId,
  draft: true,
  // 走真实的权益判据：VOLUNTEER 才会命中 UserLevel.ORIGIN 那条拒绝
  prepareType: { code: 'VOLUNTEER', desc: '智能填报' },
});
