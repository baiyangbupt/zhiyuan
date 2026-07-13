CREATE TABLE IF NOT EXISTS assistant_chat_session_pending_confirmation
(
    id                BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    tenant_id         BIGINT                              NOT NULL COMMENT '租户ID',
    chat_session_id   BIGINT                              NOT NULL COMMENT '聊天会话ID',
    pending_id        VARCHAR(64)                         NOT NULL COMMENT '待确认资源ID',
    revision          BIGINT      DEFAULT 1               NOT NULL COMMENT '独立CAS修订号',
    kind              VARCHAR(32)                         NOT NULL COMMENT '待确认类型',
    action_family     VARCHAR(64)                         NOT NULL COMMENT '动作族',
    status            VARCHAR(16)                         NOT NULL COMMENT 'active/applying/applied/cancelled/expired',
    data_value        LONGTEXT                            NOT NULL COMMENT '完整待确认快照(JSON)',
    result_code       VARCHAR(64)                         NULL COMMENT '最终结果码',
    resolved_action   VARCHAR(16)                         NULL COMMENT '最近一次状态迁移动作',
    create_time       DATETIME    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time       DATETIME    DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_pending_confirmation_tenant_session
        UNIQUE (tenant_id, chat_session_id)
)
    COMMENT '会话当前待确认快照；每个会话单活并使用独立CAS修订号';

CREATE INDEX idx_pending_confirmation_pending_id
    ON assistant_chat_session_pending_confirmation (tenant_id, pending_id);
