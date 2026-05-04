package com.ytell.zhiyuan.common.exception;

import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * @author huqitong
 */
@Data
@EqualsAndHashCode(callSuper = false)
public class BusinessException extends RuntimeException {
    private int status;

    public BusinessException(int errCode, String errMsg) {
        super(errMsg);
        status = errCode;
    }
}
