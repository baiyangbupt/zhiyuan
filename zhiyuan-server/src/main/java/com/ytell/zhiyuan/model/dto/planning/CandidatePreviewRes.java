package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 候选预览（只读）响应：**只带回一页，全量留服务器**。
 *
 * <p>契约上最要紧的三点：</p>
 * <ul>
 *   <li>每项都带 {@code entityId}（= volunteerId）——工作集记忆只认 `entityId|id`，
 *       缺了它，模型"看过候选"这件事落不进工作集；</li>
 *   <li>{@code total} 是**过滤后的全量条数**，{@code items} 只是样例：调用方必须用
 *       {@code total > items.size()} 判断"这不是全部"；</li>
 *   <li>{@code limitations} 说明这份预览哪里不可用（如
 *       {@code candidate_source_unavailable}），而不是用 500 表达。</li>
 * </ul>
 */
@Data
public class CandidatePreviewRes {
    private List<Item> items = Lists.newArrayList();
    private Integer page = 1;
    private Integer pageSize = 20;
    private Integer total = 0;
    private Integer profileVersion;
    private String dataVersion;
    private List<String> limitations = Lists.newArrayList();

    @Data
    public static class Item {
        /** 工作集记忆键：与 volunteerId 同值，但字段名按 `entityId` 给。 */
        private String entityId;
        private String volunteerId;
        private String tier;
        private String schoolId;
        private String schoolName;
        private String majorId;
        private String majorName;
        private Double finalScore;
        private Double admissionRatio;
        private Double schoolEnrollRatio;
        private Integer rankInTier;
        private Integer planNum;
        private Integer tuitionPerYear;
        private List<String> mustSubjects = Lists.newArrayList();
        private List<String> riskFlags = Lists.newArrayList();
        private List<String> reasonCodes = Lists.newArrayList();
    }
}
