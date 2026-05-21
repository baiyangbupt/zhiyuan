CREATE TABLE IF NOT EXISTS assistant_planning_behavior_event
(
    id                    BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    event_id              VARCHAR(64)                         NOT NULL COMMENT '事件ID',
    chat_session_id       BIGINT                              NOT NULL COMMENT '聊天会话ID',
    tenant_id             BIGINT                              NULL COMMENT '租户ID',
    event_type            VARCHAR(64)                         NOT NULL COMMENT '事件类型',
    mode                  VARCHAR(64)                         NULL COMMENT '操作模式',
    plan_version          INT                                 NULL COMMENT '方案版本',
    generation_mode       VARCHAR(64)                         NULL COMMENT '生成模式',
    volunteer_ids_json    LONGTEXT                            NULL COMMENT '志愿ID列表(JSON)',
    unit_ids_json         LONGTEXT                            NULL COMMENT '单元ID列表(JSON)',
    from_positions_json   LONGTEXT                            NULL COMMENT '移动前位置(JSON)',
    to_positions_json     LONGTEXT                            NULL COMMENT '移动后位置(JSON)',
    tier                  VARCHAR(32)                         NULL COMMENT '冲稳保层级',
    admission_ratio       DOUBLE                              NULL COMMENT '录取率',
    school_name           VARCHAR(255)                        NULL COMMENT '学校名称',
    major_name            VARCHAR(255)                        NULL COMMENT '专业名称',
    sort_key              VARCHAR(64)                         NULL COMMENT '排序字段',
    positive_feedback     TINYINT(1) DEFAULT 0                NOT NULL COMMENT '是否正反馈',
    snapshot_digest       VARCHAR(128)                        NULL COMMENT '状态摘要',
    create_time           DATETIME    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time           DATETIME                            NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_planning_behavior_event_event_id
        UNIQUE (event_id)
)
    COMMENT '志愿规划行为事件表';

CREATE INDEX idx_planning_behavior_event_session_type_time
    ON assistant_planning_behavior_event (chat_session_id, event_type, create_time);

CREATE INDEX idx_planning_behavior_event_session_time
    ON assistant_planning_behavior_event (chat_session_id, create_time);
