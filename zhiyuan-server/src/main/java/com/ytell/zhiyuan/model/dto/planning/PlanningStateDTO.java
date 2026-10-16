package com.ytell.zhiyuan.model.dto.planning;

import com.alibaba.fastjson.annotation.JSONField;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.google.common.collect.Lists;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.util.List;

@Data
// 本工程 lombok 1.16.16（2017）：没有 @EqualsAndHashCode.Exclude 嵌套注解，用 exclude 字段名代替
@EqualsAndHashCode(exclude = {"baselineDataValue", "baselinePoolRowId", "baselinePoolDataVersion", "baselinePoolDataValue"})
public class PlanningStateDTO {
    private Long sessionId;
    private Integer version = 0;
    private String phase = "profile_ready";
    private StaleFlagsDTO staleFlags = new StaleFlagsDTO();
    private ProfileStateDTO profileState = new ProfileStateDTO();
    private ConstraintStateDTO constraintState = new ConstraintStateDTO();
    private DataFreshnessStateDTO dataFreshnessState = new DataFreshnessStateDTO();
    private CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
    private CandidateViewStateDTO candidateViewState;
    private InitialRecommendationStateDTO initialRecommendationState = new InitialRecommendationStateDTO();
    private RecommendationOverlayStateDTO recommendationOverlayState = new RecommendationOverlayStateDTO();
    private PlanGenerationStateDTO planGenerationState = new PlanGenerationStateDTO();
    private DraftPlanStateDTO workingPlanState = new DraftPlanStateDTO();
    private OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
    private PlanAdjustmentStateDTO planAdjustmentState = new PlanAdjustmentStateDTO();
    private ReviewStateDTO reviewState = new ReviewStateDTO();
    private List<OperationLogDTO> operationLogs = Lists.newArrayList();

    /**
     * 写路径 CAS 的**基线载体**（H2 写路径统一 CAS，见
     * {@code docs/superpowers/tasks/P2-write-closed-loop/H2-WRITE-CAS-PLAN.md} §3）：
     * {@code loadPlanningState*} 之后这里是**实际落在库里的那串 data_value**（懒导入/读路径
     * 补写以"最后真正写进库里的"为准），落盘时作为
     * {@code updateDataValueIfUnchanged(row, baselineDataValue, newDataValue)} 的期望值——
     * 库里那行不再是手里这份快照时**不覆盖**（输的一方放弃或按站点策略重读合并）。
     *
     * <p>它**不参与 JSON 序列化**（不写进 data_value、也不从库里反解），只是内存态；
     * equals/hashCode 也不含它（同一份文档内容不因基线不同而"不等"）。</p>
     */
    @JSONField(serialize = false, deserialize = false)
    private String baselineDataValue;

    /**
     * 候选池大文档引用（池状态瘦身·切片1，2026-10-16 review §五-54）：非空=items 不在本行、
     * 在 {@code planningCandidatePool} 行里（读闸口回填）。行内 JSON 由
     * {@code PlanningStateService} 落盘时手工带上（{@code serialize=false} 保证任何常规
     * fastjson 序列化——含导出——都不带它）；{@code deserialize} 照读，回填判定用它。
     * Jackson {@code @JsonIgnore}：/session/state 对外 JSON 形状不变。
     */
    @JSONField(serialize = false, deserialize = true)
    @JsonIgnore
    private CandidatePoolRefDTO candidatePoolRef;

    /**
     * 池行（{@code planningCandidatePool}）写路径 CAS 的基线三件套：与 {@link #baselineDataValue}
     * 同义，但作用于池行（行 id/data_version/data_value）。同样不参与 JSON（内存态专用）。
     * 拆分行加载时由读闸口回填；旧内联行（legacy）不带，首次拆分写时按"池行未知"处理（读一次池行）。
     */
    // 三个新基线字段同样 @JsonIgnore：/session/state 是 Jackson 序列化，漏一个就会把池行
    // 整串 data_value（38MB 级）带进 API 响应——对外形状必须与拆分前一致。
    @JSONField(serialize = false, deserialize = false)
    @JsonIgnore
    private Long baselinePoolRowId;

    @JSONField(serialize = false, deserialize = false)
    @JsonIgnore
    private Integer baselinePoolDataVersion;

    @JSONField(serialize = false, deserialize = false)
    @JsonIgnore
    private String baselinePoolDataValue;

    /**
     * Backward-compatible alias for persisted 3.0.x planning state and older agent/frontend callers.
     * New code should use workingPlanState.
     */
    @Deprecated
    public DraftPlanStateDTO getDraftPlanState() {
        return workingPlanState;
    }

    /**
     * Backward-compatible alias for persisted 3.0.x planning state and older agent/frontend callers.
     * New code should use workingPlanState.
     */
    @Deprecated
    public void setDraftPlanState(DraftPlanStateDTO draftPlanState) {
        if (draftPlanState != null || this.workingPlanState == null) {
            this.workingPlanState = draftPlanState;
        }
    }
}
