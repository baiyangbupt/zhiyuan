CREATE TABLE IF NOT EXISTS assistant_planning_data_freshness_schedule
(
    id                       BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    chat_session_id          BIGINT                              NOT NULL COMMENT '聊天会话ID',
    tenant_id                BIGINT                              NULL COMMENT '租户ID',
    prepare_type             VARCHAR(32)                         NULL COMMENT '填报类型',
    province_code            VARCHAR(32)                         NULL COMMENT '省份编码',
    province_name            VARCHAR(64)                         NULL COMMENT '省份名称',
    exam_year                INT                                 NULL COMMENT '高考年份',
    session_status           VARCHAR(32)                         NULL COMMENT '会话状态',
    session_create_time      DATETIME                            NULL COMMENT '会话创建时间',
    last_accessed_at         DATETIME                            NULL COMMENT '最近访问时间',
    last_checked_at          DATETIME                            NULL COMMENT '最近成功检查时间',
    next_check_at            DATETIME                            NULL COMMENT '下次计划检查时间',
    check_interval_minutes   INT         DEFAULT 300             NOT NULL COMMENT '检查间隔分钟',
    last_check_source        VARCHAR(32)                         NULL COMMENT '最近检查来源',
    last_check_status        VARCHAR(32)                         NULL COMMENT '最近检查状态',
    source_data_hash         VARCHAR(128)                        NULL COMMENT '本地源数据摘要',
    latest_source_data_hash  VARCHAR(128)                        NULL COMMENT '最近检查到的上游源数据摘要',
    fail_count               INT         DEFAULT 0               NOT NULL COMMENT '连续失败次数',
    last_error               VARCHAR(1024)                       NULL COMMENT '最近失败原因',
    last_failed_at           DATETIME                            NULL COMMENT '最近失败时间',
    enabled                  TINYINT(1)  DEFAULT 1               NOT NULL COMMENT '是否纳入后台巡检',
    create_time              DATETIME    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time              DATETIME                            NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_planning_data_freshness_schedule_session
        UNIQUE (chat_session_id)
)
    COMMENT '招生计划数据新鲜度后台巡检索引表';

CREATE INDEX idx_planning_data_freshness_schedule_due
    ON assistant_planning_data_freshness_schedule (enabled, next_check_at, province_code, session_create_time);

CREATE INDEX idx_planning_data_freshness_schedule_status
    ON assistant_planning_data_freshness_schedule (last_check_status, next_check_at);
