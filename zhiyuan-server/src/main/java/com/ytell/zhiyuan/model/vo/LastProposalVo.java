package com.ytell.zhiyuan.model.vo;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;


/**
 * 会话里**最后一条**提案的落定状态——给浏览器**冷加载**用。
 *
 * <p>为什么要有它：卡片状态今天只活在**事件流**里（`proposal.preview` / {@code conversationAction.result}），
 * 而冷加载时客户端没有游标——`conversationCursor.mjs` 的口径是"游标不落盘"——服务端那条路
 * 只补**在飞回合**（`app/server.py` 的 `_replay_active_turn`），已结束回合的卡片事件一条都不补，
 * 于是刷新/重连后提案卡**重建不出来**（F13 用例的第③条）。
 *
 * <p>消息正文走 REST（`/message/page`），提案状态也走 REST 是同一条思路：
 * 会话详情里带上"最后一条提案 + 它的动作状态"，前端据此把卡画出来。
 *
 * <p>数据源是**待确认那一条**（`assistant_chat_session_pending_confirmation` 的当前行）：
 * 它天然带着"提案是谁"（`proposalId`）与"动作落定没有"（`status`）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class LastProposalVo {

    /** 卡片按它找动作回包：等于待确认的 `pendingId`（不是编译器的 `ugp_…`）。 */
    private String proposalRef;

    /** Java 编译器产出的提案号（`ugp_…`）。 */
    private String proposalId;

    /** 展示状态：active / applying / applied / cancelled / expired / failed；执行失败不显示为过期。 */
    private String actionStatus;

    /** 提案编译时的计划版本（`dataValue.sourceVersion`）。 */
    private Integer sourceVersion;

    /** 待确认的修订号（CAS 计数器，不是计划版本）。 */
    private Long revision;

    /** 待确认行的 kind（前端兜底卡用来选标题口径）。 */
    private String kind;

    /** 冻结提案的展示字段：冷加载兜底卡据此恢复标题/摘要/影响/状态与按钮。 */
    private String title;
    private String summary;
    private String impact;
    private String status;
    private Boolean requiresConfirmation;
    /** 旧审查暂停时，review_check 卡只能取消、不能确认；user_goal 卡不受影响。 */
    private Boolean reviewPaused;
    private String disabledReason;
    private String strategy;

    /**
     * 补录族的**结构化明细**（`dataValue.scoreSummary`：省份/科类/批次/各科/总分/位次）——
     * 冷加载兜底卡靠它把"更新成绩"渲染成一张像样的卡（2026-10-08：此前只给 ref，
     * 卡片落兜底标题"方案调整预览"、明细全丢 ✗）；方案调整族为 null。
     */
    private Object scoreSummary;
}
