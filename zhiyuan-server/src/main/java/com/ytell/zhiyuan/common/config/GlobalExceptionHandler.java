package com.ytell.zhiyuan.common.config;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.common.exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.bind.annotation.ResponseStatus;

/**
 * @author huqitong
 */
@ControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    @ResponseStatus(value = HttpStatus.OK)
    @ResponseBody
    public BaseResponse handlerBusinessException(BusinessException ex) {
        log.error(ex.getMessage(), ex);
        return BaseResponse.error(ex.getStatus(), ex.getMessage());
    }

    @ExceptionHandler(Exception.class)
    @ResponseStatus(value = HttpStatus.OK)
    @ResponseBody
    public BaseResponse handlerException(Exception ex) {
        log.error(ex.getMessage(), ex);
        return BaseResponse.error(-1, "系统错误");
    }
}
