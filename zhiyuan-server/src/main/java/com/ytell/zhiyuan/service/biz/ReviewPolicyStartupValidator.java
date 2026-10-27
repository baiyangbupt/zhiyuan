package com.ytell.zhiyuan.service.biz;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;

/** 启动即校验审查策略，非法配置直接失败，避免请求期才发现。 */
@Component
public class ReviewPolicyStartupValidator {

    @Value("${planning.review.mode:}")
    private String configuredMode;

    @PostConstruct
    public void validate() {
        ReviewPolicy.configureFromSpring(configuredMode);
        ReviewPolicy.validateConfiguration();
    }
}
