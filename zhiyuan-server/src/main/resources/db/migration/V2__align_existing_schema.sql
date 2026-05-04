SET @assistant_user_credential_channel_sql = (
    SELECT IF(
        EXISTS(
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'assistant_user_credential'
              AND COLUMN_NAME = 'channel'
        ),
        'SELECT 1',
        "ALTER TABLE assistant_user_credential ADD COLUMN channel VARCHAR(64) NULL DEFAULT 'gaotu' COMMENT '渠道'"
    )
);
PREPARE assistant_user_credential_channel_stmt FROM @assistant_user_credential_channel_sql;
EXECUTE assistant_user_credential_channel_stmt;
DEALLOCATE PREPARE assistant_user_credential_channel_stmt;

SET @assistant_user_base_limit_settings_sql = (
    SELECT IF(
        EXISTS(
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'assistant_user_base'
              AND COLUMN_NAME = 'limit_settings'
        ),
        'SELECT 1',
        "ALTER TABLE assistant_user_base ADD COLUMN limit_settings TEXT NULL COMMENT '限制设置'"
    )
);
PREPARE assistant_user_base_limit_settings_stmt FROM @assistant_user_base_limit_settings_sql;
EXECUTE assistant_user_base_limit_settings_stmt;
DEALLOCATE PREPARE assistant_user_base_limit_settings_stmt;

SET @assistant_user_base_expired_date_sql = (
    SELECT IF(
        EXISTS(
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'assistant_user_base'
              AND COLUMN_NAME = 'expired_date'
        ),
        'SELECT 1',
        "ALTER TABLE assistant_user_base ADD COLUMN expired_date DATETIME NULL COMMENT '账号过期时间'"
    )
);
PREPARE assistant_user_base_expired_date_stmt FROM @assistant_user_base_expired_date_sql;
EXECUTE assistant_user_base_expired_date_stmt;
DEALLOCATE PREPARE assistant_user_base_expired_date_stmt;

SET @assistant_user_base_user_level_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'assistant_user_base'
      AND COLUMN_NAME = 'user_level'
);
SET @assistant_user_base_user_level_type = (
    SELECT DATA_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'assistant_user_base'
      AND COLUMN_NAME = 'user_level'
    LIMIT 1
);
SET @assistant_user_base_user_level_sql = IF(
    @assistant_user_base_user_level_exists = 0,
    "ALTER TABLE assistant_user_base ADD COLUMN user_level VARCHAR(32) NULL COMMENT '用户等级'",
    IF(
        @assistant_user_base_user_level_type <> 'varchar',
        "ALTER TABLE assistant_user_base MODIFY COLUMN user_level VARCHAR(32) NULL COMMENT '用户等级'",
        'SELECT 1'
    )
);
PREPARE assistant_user_base_user_level_stmt FROM @assistant_user_base_user_level_sql;
EXECUTE assistant_user_base_user_level_stmt;
DEALLOCATE PREPARE assistant_user_base_user_level_stmt;

SET @assistant_user_base_channel_sql = (
    SELECT IF(
        EXISTS(
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'assistant_user_base'
              AND COLUMN_NAME = 'channel'
        ),
        'SELECT 1',
        "ALTER TABLE assistant_user_base ADD COLUMN channel VARCHAR(64) NULL DEFAULT 'gaotu' COMMENT '渠道'"
    )
);
PREPARE assistant_user_base_channel_stmt FROM @assistant_user_base_channel_sql;
EXECUTE assistant_user_base_channel_stmt;
DEALLOCATE PREPARE assistant_user_base_channel_stmt;

INSERT INTO assistant_bot_info
    (id, tenant_id, nick_name, avatar_url, introduce, create_time)
SELECT 1, 1, '本地测试机器人', '', 'local bot', NOW()
WHERE NOT EXISTS (
    SELECT 1
    FROM assistant_bot_info
    WHERE id = 1
);
