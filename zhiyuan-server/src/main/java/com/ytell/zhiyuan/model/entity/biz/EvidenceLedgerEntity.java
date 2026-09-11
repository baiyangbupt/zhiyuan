package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

/** Java 签发的权威证据台账记录。 */
@Data
@TableName("evidence_ledger")
public class EvidenceLedgerEntity {

    @TableId(value = "evidence_id", type = IdType.INPUT)
    private String evidenceId;
    private Long tenantId;
    private Long chatSessionId;
    private String threadId;
    private String sourceSystem;
    private String paramsDigest;
    private String dataVersion;
    private String algorithmVersion;
    private String admissionMode;
    private String admissionUnitId;
    private String groupCode;
    private Integer stateVersion;
    private String scopeJson;
    private String limitationsJson;
    private Date observedAt;
    private Date expiresAt;
}
