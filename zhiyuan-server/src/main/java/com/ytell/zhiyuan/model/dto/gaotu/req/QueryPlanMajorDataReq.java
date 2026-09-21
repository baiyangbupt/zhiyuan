package com.ytell.zhiyuan.model.dto.gaotu.req;

import lombok.Data;

/**
 * 招生计划查询入参。
 *
 * <p>上游 `PlanMajorDataRequest` 的镜像：**不含分数**——这是计划数据能脱离
 * "分数带"取数的依据（见 docs/contracts/upstream-authoritative-data-map.md）。
 */
@Data
public class QueryPlanMajorDataReq {
    private String schoolId;
    private String areaId;
    private String year;
    private String subject;
    private String batch;
    private String schoolUnitId;
}
