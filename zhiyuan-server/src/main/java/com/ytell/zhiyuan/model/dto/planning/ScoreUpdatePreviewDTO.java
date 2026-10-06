package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 补录成绩（score_update 动作族）的**只读预览**，prepare 与 preview 两个入口共用。
 *
 * <p>它是卡片上"给人看的那一份"：`summary` 里的字段就是用户要确认的内容
 * （省份/科类/批次/总分/位次/各科）——摘要由 **Java 按合并后的成绩算**，不采信模型
 * 在文本里的复述（模型只负责表达"要改什么"，权威值在这条链上算）。</p>
 *
 * <p>`sourceVersion` 是本次预览依据的规划状态版本：卡片把它带回来做版本守门
 * （确认时与快照/计划版本比对），pending 的 dataValue 里落的也是同一个值。</p>
 */
@Data
public class ScoreUpdatePreviewDTO {

    /** 与 PrepareResultDTO 的状态词同义：`ready` = 可以确认；`blocked` = 只解释原因。 */
    private String status;

    private Integer sourceVersion;

    private Boolean requiresConfirmation;

    /**
     * 结构化摘要（省份/科类/批次/总分/位次/各科/优势学科）。
     * 用 Map 而不是再定一个 DTO：字段是**给人看的展示集**，网关只做透传，
     * 不参与任何判定（判定全在 Java 的校验/合并逻辑里）。
     */
    private Map<String, Object> summary = new LinkedHashMap<String, Object>();
}
