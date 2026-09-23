package com.ytell.zhiyuan.model.dto.volunteer;

import lombok.Data;

/**
 * 一条**结构化**的打分理由（P1d）。
 *
 * <p>与 {@code college_remark} 那串中文并存：那串是拼给人看的旧通道，这一条是给对话层
 * 用的稳定通道。{@code code} 由 Java 定义（raw 标签不出门），{@code delta} 是 rank 在
 * 调整时**观测**到的增量，不是我们事后推断出来的。
 *
 * <p>{@code weight} 可以为 {@code null}：这一项没有对应权重时**省略**，不补 0——
 * 补 0 会让"没有这个权重"与"权重是零"长得一样。
 */
@Data
public class RankReasonDTO {

    /** 稳定标识，由本层定义（例如 {@code school.positive}、{@code major.tuition.high}）。 */
    private String code;

    /** 给人看的中文短语。 */
    private String name;

    /** 该因子在熵权/查询权重里的权重；取不到就不设。 */
    private Double weight;

    /** 这次调整对分数做了什么（差值，正向为加、负向为减）。 */
    private Double delta;

    /** 一句话说明这条为什么加/减分。 */
    private String reason;
}
