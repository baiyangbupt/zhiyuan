CREATE TABLE IF NOT EXISTS integration_session_request
(
    id                  BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    tenant_id           BIGINT                              NOT NULL COMMENT '租户ID',
    user_id             BIGINT                              NOT NULL COMMENT '本系统授权用户ID',
    platform            VARCHAR(64)                         NULL COMMENT 'pf渠道',
    external_request_id VARCHAR(128)                        NOT NULL COMMENT '外部幂等请求ID',
    request_hash        VARCHAR(64)                         NOT NULL COMMENT '请求体hash',
    chat_session_id     BIGINT                              NULL COMMENT '创建出的会话ID',
    status              VARCHAR(32) DEFAULT 'PROCESSING'    NOT NULL COMMENT 'PROCESSING/SUCCESS/FAILED',
    error_message       VARCHAR(1024)                       NULL COMMENT '失败原因',
    create_time         DATETIME    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time         DATETIME                            NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_integration_session_request
        UNIQUE (tenant_id, user_id, external_request_id)
)
    COMMENT '外部初始化会话幂等记录表';

CREATE INDEX idx_integration_session_request_session
    ON integration_session_request (chat_session_id);
