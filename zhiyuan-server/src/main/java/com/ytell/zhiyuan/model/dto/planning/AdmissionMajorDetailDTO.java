package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/** 院校专业组下挂的专业明细；不参与专业组风险层级计算。 */
@Data
public class AdmissionMajorDetailDTO {
    private String majorId;
    private String majorName;
    private String majorCode;
    private Double majorAdmissionRate;
}
