package com.ytell.zhiyuan.common.exception;

import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 对话访问被拒。
 *
 * <p>与既有 `BusinessException`（HTTP 200 + body.code）分开，是为了让
 * **新路径能返回真实的 401/403**：浏览器与代理需要按传输层状态决定
 * "要不要重新登录"，而 body 里的业务码到不了那一层。
 *
 * <p>既有接口的状态码语义不变——那是兼容问题，不能全站改。
 */
@Data
@EqualsAndHashCode(callSuper = false)
public class ConversationAccessException extends RuntimeException {
    private final int status;

    public ConversationAccessException(int status, String message) {
        super(message);
        this.status = status;
    }
}
