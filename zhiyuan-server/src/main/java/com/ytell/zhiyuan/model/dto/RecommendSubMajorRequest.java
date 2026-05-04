package com.ytell.zhiyuan.model.dto;

import lombok.Data;

@Data
public class RecommendSubMajorRequest {
    private CreateSessionReq studentinfo;
    private Integer topN;
    
}
