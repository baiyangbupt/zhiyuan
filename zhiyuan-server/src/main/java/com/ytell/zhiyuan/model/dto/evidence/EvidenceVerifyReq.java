package com.ytell.zhiyuan.model.dto.evidence;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/** 批量核验请求：一个回合一次调用，提交本回合引用的全部 evidenceId。 */
@Data
public class EvidenceVerifyReq {

    private Long tenantId;
    private Long chatSessionId;
    private String threadId;
    private List<String> evidenceIds = new ArrayList<String>();
}
