package com.ytell.zhiyuan.common.exception;

public class ReviewFixStaleException extends RuntimeException {
    public ReviewFixStaleException() {
        super("review_fix_stale");
    }
}
