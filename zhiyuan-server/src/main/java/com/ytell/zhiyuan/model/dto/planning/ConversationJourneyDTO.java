package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 对话旅程的紧凑事实块（J1）。
 *
 * <p>只读派生：不落库、不是第二套业务真值。Java 是唯一生产者；Agent 只消费，
 * 不根据 staleFlags 的 null/非 null 重新推导（那会恒 true）。</p>
 */
@Data
public class ConversationJourneyDTO {
    /** 画像硬事实是否齐全：省份+年份+批次+科类+（成绩或位次）。 */
    private Boolean hasProfile = false;
    /** 缺失的画像键：province/examYear/batch/subjectType/scoreOrRank。 */
    private List<String> profileMissing = Lists.newArrayList();
    private Boolean hasCandidates = false;
    private Integer candidateEntryCount = 0;
    private Integer candidateSourceVersion;
    /** ordered ∪ working 的 items/units 任一非空。 */
    private Boolean hasPlan = false;
    /** 展示用条目数：先取在用的方案，再按 admissionMode 优先其对应形状。 */
    private Integer planEntryCount = 0;
    /** 只数 ordered 且按 admissionMode 取对应形状；解读/审查的正式方案判据。 */
    private Integer orderedEntryCount = 0;
    private Boolean planInterpretable = false;
    /** 已确认目标数与业务 helper 同口径的当前数（供 add_units 目标数阻断）。 */
    private Integer selectionTargetCount;
    private Integer selectionCurrentCount = 0;
    /** 唯一计数器（planningState.version），不是内容版本。 */
    private Integer planVersion = 0;
    /** 方案内容指纹：ordered 优先；working 回退带 "working|" 前缀。 */
    private String planContentDigest;
    /** fresh | stale | absent。 */
    private String candidateFreshness = "absent";
    private String planFreshness = "absent";
    /** 方案结构有过调整（markPlanStructureStale）；参考信号，不参与 planFreshness。 */
    private Boolean planAdjustmentStale = false;
    private String reviewFreshness = "absent";
    /** none | candidates | plan | review；按 candidates→plan→review 取第一个非 fresh。 */
    private String refreshRequirement = "none";
    private Integer reviewSourceVersion;
    private Boolean reviewStale = false;
    private Boolean tierQuotaGoal = false;
    /** 六个 flag 的并集 + reasonCode/message 非空；Java 算好，Agent 只读布尔。 */
    private Boolean stale = false;
    private String staleReasonCode;
    private String staleMessage;
    /** active | applying；其余状态不暴露。 */
    private String pendingStatus;
}
