package com.ytell.zhiyuan.model.dto.gaotu.req;

import lombok.Data;

/** 院校资讯列表入参（章程索引）。 */
@Data
public class NewsPageReq {
    private String schoolId;
    private Integer current;
    private Integer size;
}
