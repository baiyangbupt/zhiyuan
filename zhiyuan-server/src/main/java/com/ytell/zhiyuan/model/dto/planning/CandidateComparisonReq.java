package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 同口径并列请求。
 *
 * <p>实体由调用方给**已确认的 ID 与已取到的值**：本接口不取数。取数在各自的
 * 来源链路上（那里签证据），这里只负责那件调用方做不到的事——
 * **判断这些值能不能放在一张表里比**。</p>
 */
@Data
public class CandidateComparisonReq {

    /** 2–5 个实体。少于 2 个不是比较，多于 5 个表格读不过来。 */
    private List<ComparisonEntityDTO> entities = new ArrayList<ComparisonEntityDTO>();

    /** 要比较的维度；不传则用服务端白名单全集。 */
    private List<String> dimensions = new ArrayList<String>();
}
