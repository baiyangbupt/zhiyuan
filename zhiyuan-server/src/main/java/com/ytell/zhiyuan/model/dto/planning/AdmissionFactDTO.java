package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/** 招生单元级权威事实。录取率由招生数据服务提供，本 DTO 不重新计算。 */
@Data
public class AdmissionFactDTO {
    private String admissionUnitId;
    private String admissionMode;
    private String schoolId;
    private String schoolName;
    private String majorId;
    private String majorName;
    private String groupCode;
    private List<AdmissionMajorDetailDTO> majorItems = new ArrayList<AdmissionMajorDetailDTO>();
    private Double unitAdmissionRate;
    private String riskTier;
    private String provinceCode;
    private Integer year;
    private String batch;
    private String dataVersion;
    private String algorithmVersion;
    private String observedAt;
    private List<String> limitations = new ArrayList<String>();
}
