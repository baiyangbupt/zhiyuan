package com.ytell.zhiyuan.model.dto.evidence;

import lombok.Data;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 一次证据签发所需的全部输入。 */
@Data
public class EvidenceSignRequest {

    /** 取数来源，如 gaotu.schoolMajorScoreLine。 */
    private String sourceSystem;
    /** 签发时观察到的上游数据版本；缺失则不签发。 */
    private String dataVersion;
    /** 查询参数，用于计算 paramsDigest。 */
    private Map<String, ?> params = new LinkedHashMap<String, Object>();
    /** 归属范围；不完整则不签发。 */
    private EvidenceScope scope = EvidenceScope.none();
    private String algorithmVersion;
    private String admissionMode;
    private String admissionUnitId;
    private String groupCode;
    private Integer stateVersion;
    private List<String> limitations = new ArrayList<String>();

    public static EvidenceSignRequest query(String sourceSystem, String dataVersion,
                                            Map<String, ?> params, EvidenceScope scope) {
        EvidenceSignRequest request = new EvidenceSignRequest();
        request.setSourceSystem(sourceSystem);
        request.setDataVersion(dataVersion);
        if (params != null) {
            request.setParams(params);
        }
        request.setScope(scope == null ? EvidenceScope.none() : scope);
        return request;
    }
}
