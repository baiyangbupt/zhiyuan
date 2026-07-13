CREATE TABLE IF NOT EXISTS assistant_planning_pending_command
(
    id                    BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    tenant_id             BIGINT                              NOT NULL COMMENT '租户ID',
    chat_session_id       BIGINT                              NOT NULL COMMENT '聊天会话ID',
    pending_id            VARCHAR(64)                         NOT NULL COMMENT '待确认资源ID',
    operation_id          VARCHAR(64)                         NOT NULL COMMENT '幂等操作ID',
    command_type          VARCHAR(48)                         NOT NULL COMMENT '命令类型',
    expected_plan_version INT                                 NOT NULL COMMENT '预期规划版本',
    status                VARCHAR(16)                         NOT NULL COMMENT 'running/succeeded',
    result_json           LONGTEXT                            NULL COMMENT '最终命令结果(JSON)',
    create_time           DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time           DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_planning_pending_command_operation
        UNIQUE (operation_id)
)
    COMMENT 'pending 多步规划命令幂等日志';

CREATE INDEX idx_planning_pending_command_session_pending
    ON assistant_planning_pending_command (tenant_id, chat_session_id, pending_id);
