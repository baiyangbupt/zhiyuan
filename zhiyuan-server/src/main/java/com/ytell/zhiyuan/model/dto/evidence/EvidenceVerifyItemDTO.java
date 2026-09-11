package com.ytell.zhiyuan.model.dto.evidence;

import lombok.Data;

/** 单条证据的核验结果。 */
@Data
public class EvidenceVerifyItemDTO {

    /** valid / stale / expired / unknown */
    private String status;
    private String sourceSystem;
    private String paramsDigest;
    private String dataVersion;
    private String observedAt;
    private String expiresAt;

    public static EvidenceVerifyItemDTO of(String status) {
        EvidenceVerifyItemDTO item = new EvidenceVerifyItemDTO();
        item.setStatus(status);
        return item;
    }
}
