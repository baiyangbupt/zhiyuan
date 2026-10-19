package com.ytell.zhiyuan.common.config;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.common.exception.ReviewFixStaleException;
import org.springframework.http.ResponseEntity;
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

    /**
     * 对话访问被拒：返回**真实 HTTP 状态**（401/403）。
     *
     * <p>刻意不加 `@ResponseStatus(HttpStatus.OK)`：新路径需要传输层状态，
     * 而本类对 BusinessException 的 200 语义保持不变。
     */
    @ExceptionHandler(ConversationAccessException.class)
    @ResponseBody
    public ResponseEntity<BaseResponse> handlerConversationAccess(ConversationAccessException ex) {
        log.warn("conversation access denied: {}", ex.getMessage());
        return ResponseEntity.status(ex.getStatus())
                .body(BaseResponse.error(ex.getStatus(), ex.getMessage()));
    }

    @ExceptionHandler(ReviewFixStaleException.class)
    @ResponseBody
    public ResponseEntity<BaseResponse> handlerReviewFixStale(ReviewFixStaleException ex) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(BaseResponse.error(40905, ex.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    @ResponseStatus(value = HttpStatus.OK)
    @ResponseBody
    public BaseResponse handlerException(Exception ex) {
        log.error(ex.getMessage(), ex);
        return BaseResponse.error(-1, "系统错误");
    }
}
