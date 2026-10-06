package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 候选预览（只读）请求。
 *
 * <p>与 {@link CandidatePoolQueryReq} 是**两条路**：那条查的是会话里**已落盘**的候选池
 * （顺带会刷新 recommendation overlay → 写规划状态），这条是"不落盘地重算一次候选并只看
 * 前若干条"。所以这里没有 sort（顺序由推荐流水线自己定，重排会把口径藏起来）。</p>
 */
@Data
public class CandidatePreviewReq {
    private CandidatePoolQueryReq.Filters filters = new CandidatePoolQueryReq.Filters();
    private Integer page = 1;
    private Integer pageSize = 20;
}
