SET @assistant_planning_behavior_event_payload_sql = (
    SELECT IF(
        EXISTS(
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'assistant_planning_behavior_event'
              AND COLUMN_NAME = 'event_payload_json'
        ),
        'SELECT 1',
        "ALTER TABLE assistant_planning_behavior_event ADD COLUMN event_payload_json LONGTEXT NULL COMMENT '事件详细载荷(JSON)' AFTER snapshot_digest"
    )
);
PREPARE assistant_planning_behavior_event_payload_stmt FROM @assistant_planning_behavior_event_payload_sql;
EXECUTE assistant_planning_behavior_event_payload_stmt;
DEALLOCATE PREPARE assistant_planning_behavior_event_payload_stmt;
