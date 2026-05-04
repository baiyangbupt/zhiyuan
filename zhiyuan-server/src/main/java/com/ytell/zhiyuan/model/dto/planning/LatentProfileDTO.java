package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class LatentProfileDTO {
    private FutureDevelopmentDTO futureDevelopment = new FutureDevelopmentDTO();
    private InterestPersonalityDTO interestPersonality = new InterestPersonalityDTO();
    private FamilyContextDTO familyContext = new FamilyContextDTO();
}
