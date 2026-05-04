package com.ytell.zhiyuan.model.enums;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum UserLevel {
    SUPER_VIP(365,500,200),
    VIP(365,20,10),
    ORIGIN(7,5,2);

    private final int expiredDays;
    private final int createSessionLimit;
    private final int modifyScoreLimit;

    public static UserLevel  convertGaotuLevel(Integer userType){
        if(userType==null){
            return ORIGIN;
        }

        if(userType.equals(0)){
            return SUPER_VIP;
        }
        if(userType.equals(1)){
            return VIP;
        }
        if(userType.equals(2)){
            return ORIGIN;
        }
        return ORIGIN;

    }
}
