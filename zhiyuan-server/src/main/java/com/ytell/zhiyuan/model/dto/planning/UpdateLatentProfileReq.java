package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class UpdateLatentProfileReq {
    private FutureDevelopmentDTO futureDevelopment;
    private InterestPersonalityDTO interestPersonality;
    private FamilyContextDTO familyContext;
}
