package com.ytell.zhiyuan.model.req;

import lombok.Data;

/**
 * 更新学费区间请求
 */
@Data
public class UpdateTuitionRangeReq {

    /**
     * 学费下限（单位：元/年）
     */
    private Integer min;

    /**
     * 学费上限（单位：元/年）
     */
    private Integer max;
}





