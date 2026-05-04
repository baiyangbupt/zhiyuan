package com.ytell.zhiyuan.model.dto.gaotu.res;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.Getter;

import java.util.Date;

@Data
public class UserRightsByUserIdRes {
    private Integer userType;
    private Date expirationTime;// 到期时间，仅当userType为1时返回


    @Getter
    @AllArgsConstructor
    public enum UserTypeEnum{
        WHITELIST(0), PURCHASED(1), UN_PURCHASED(2);
        private final Integer dbValue;
    }
}
