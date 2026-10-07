package com.ytell.zhiyuan.model.dto.inner;

import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import lombok.Data;

import java.util.List;

/**
 * 专业方向推荐预览的 data 形状（只读）。
 *
 * <p>条目字段照 rank 服务的 {@link RecommendSubMajorResponse.MajorRecommendItem}：
 * {@code score} 是熵权法加权后的**综合推荐分**，四个维度分是它的构成
 * （性别分布适配 gender_index / 满意度 satisfy_index / 薪酬 salary_avg / 热度 hot_index）。
 * 跨专业可比的是**排序**，不是分数绝对值。</p>
 *
 * <p>不可用（无档案/无分数/画像缺 rank 必读字段）时本对象不出现在响应里：
 * 那条路径是 {@code data: null + 原因码（msg）}——见
 * {@code MajorRecommendPreviewService}。</p>
 */
@Data
public class MajorRecommendPreviewRes {

    private Long chatSessionId;

    /** 实际生效的条数上限（请求 topN 与硬上限 8 取小）。 */
    private Integer topN;

    /** 按综合推荐分降序的 topN 切片。 */
    private List<RecommendSubMajorResponse.MajorRecommendItem> items;

    /** 如实标注的边界（如结果为空）；可用路径下通常为空列表，不是 null。 */
    private List<String> limitations;
}
