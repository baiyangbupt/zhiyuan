package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class ProfileStateDTO {
    private ExplicitProfileDTO explicitProfile = new ExplicitProfileDTO();
    private LatentProfileDTO latentProfile = new LatentProfileDTO();
    private PhysicalConstraintsDTO physicalConstraints = new PhysicalConstraintsDTO();
}
