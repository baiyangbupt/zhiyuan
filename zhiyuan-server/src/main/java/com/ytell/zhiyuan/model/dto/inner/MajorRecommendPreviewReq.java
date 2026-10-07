package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

/**
 * 专业方向推荐预览请求（只读）。
 *
 * <p>身份即**会话**：画像（userScoreDetail）挂在 chatSessionId 上，不另收 tenant/user——
 * 这条是内部端点，归属由调用方（Agent 的受信会话绑定）保证。</p>
 */
@Data
public class MajorRecommendPreviewReq {

    /** 会话ID：画像从这里取（缺行如实回"没有档案"，不造数）。 */
    private Long chatSessionId;

    /** 返回条数上限；缺省 8。**硬上限 8**：超过按 8 截断，不报错。 */
    private Integer topN;
}
