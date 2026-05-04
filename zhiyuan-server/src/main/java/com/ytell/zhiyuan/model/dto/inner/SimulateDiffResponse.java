package com.ytell.zhiyuan.model.dto.inner;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 模拟对比响应 —— 描述画像变更前后志愿方案的差异（基于水位线）。
 *
 * promoted: 各区间中，新进入水位线以内（优选）的学校
 * demoted:  各区间中，移出水位线以内（优选）的学校
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class SimulateDiffResponse {

    /** 变更前的层级统计 */
    private TierSummary before;

    /** 变更后的层级统计 */
    private TierSummary after;

    /** 各区间水位线内新进入的学校（之前在水位线外或不存在，现在进入水位线内） */
    private List<SchoolDiff> promoted;

    /** 各区间水位线内移出的学校（之前在水位线内，现在掉到水位线外或被移除） */
    private List<SchoolDiff> demoted;

    // ---- inner classes ----

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class TierSummary {
        private int sprintCount;
        private int safeCount;
        private int protectCount;
        private int totalCount;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class SchoolDiff {
        private String schoolId;
        private String schoolName;
        /** 所属区间：sprint / safe / protect */
        private String tier;
    }
}
