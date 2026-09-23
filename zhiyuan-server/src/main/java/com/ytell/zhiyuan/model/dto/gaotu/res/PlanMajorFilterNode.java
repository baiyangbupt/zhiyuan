package com.ytell.zhiyuan.model.dto.gaotu.res;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;

/**
 * 招生计划筛选条件树的节点。
 *
 * <p>上游返回的是一棵**四层固定嵌套**的树：年份 → 科类 → 批次 → 招生单元。
 * 层与层用的是同一个形状（{@code value/label/children}），所以这里也用一个类型，
 * 不按层拆成四个 DTO——拆了就得靠字段名去猜哪一层是哪一层，而它们本来就没有名字。</p>
 *
 * <p>最后一层的 {@code value} 是**招生单位编号**（{@code schoolUnitId}），
 * 也就是 {@code planMajorDataList} 的必填入参；{@code code} 是该省的院校代码。
 * 显式写在这里，是因为这个字段的含义光看名字（value）看不出来。</p>
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class PlanMajorFilterNode {

    /** 依次是：年份、科类、批次；最后一层是招生单位编号。 */
    private String value;

    /** 人类可读的标签（"2025"、"综合"、"第一段"、学校名）。 */
    private String label;

    /** 该省的院校代码，只有最后一层有。 */
    private String code;

    private List<PlanMajorFilterNode> children;
}
