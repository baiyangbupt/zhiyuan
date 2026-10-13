package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 软偏好（**legacy 只读**，4.0 起；2026-10-13 队列 21 定稿）。
 *
 * <p>4.0 权威意向字段为 {@code hardPlanningObjectives}（priorityRules/coverageRequirements/
 * tierQuotaGoal）+ {@code hardConstraints}；本字段仅**为兼容旧会话**保留（旧数据可能带值，
 * 读取方继续读：模型快照/横幅/解释服务），**现网已无写者**（写链恒发
 * {@code intentMode=constraint}）。**不删字段、不删读分支；勿在写链新增逻辑**。</p>
 */
@Data
public class SoftPreferencesDTO {
    private List<String> preferRegions = Lists.newArrayList();
    private List<String> preferMajors = Lists.newArrayList();
    private List<String> preferSchools = Lists.newArrayList();
    private List<String> avoidRegions = Lists.newArrayList();
    private List<String> avoidMajors = Lists.newArrayList();
    private List<String> avoidSchools = Lists.newArrayList();
    private String riskStyle;
}
