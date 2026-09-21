package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 完整方案的**无副作用**预览。
 *
 * <p>它不改正式志愿表、不改约束、不改画像——只在 DTO 副本上演算。
 * `status` 为 `ready` 之前**不能**编译出可确认的 Pending：
 * 预览不成立时让用户确认，等于让他确认一份不存在的方案。
 */
@Data
public class PlanPreviewDTO {
    public static final String STATUS_READY = "ready";
    public static final String STATUS_INFEASIBLE = "infeasible";
    public static final String STATUS_NEEDS_CLARIFICATION = "needs_clarification";

    private String previewId;
    /** 预览所依据的工作区版本。 */
    private Integer sourceVersion;
    private Integer profileVersion;
    private String candidateArtifactId;
    private FrozenPlanPayloadDTO frozenPlan;
    private List<Object> orderedUnits = new ArrayList<Object>();
    private Object reviewReport;
    /** 与当前正式表的差异。**不以模型自然语言代替**。 */
    private Object diff;
    private String status;
    private List<String> limitations = new ArrayList<String>();
    private String digest;
}
