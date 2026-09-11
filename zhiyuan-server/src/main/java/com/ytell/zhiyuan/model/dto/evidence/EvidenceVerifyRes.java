package com.ytell.zhiyuan.model.dto.evidence;

import lombok.Data;

import java.util.LinkedHashMap;
import java.util.Map;

/** 批量核验结果：evidenceId → 四态。 */
@Data
public class EvidenceVerifyRes {

    private Map<String, EvidenceVerifyItemDTO> results = new LinkedHashMap<String, EvidenceVerifyItemDTO>();
}
