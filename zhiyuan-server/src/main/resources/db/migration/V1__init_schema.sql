CREATE TABLE IF NOT EXISTS assistant_bot_info
(
    id          BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    tenant_id   BIGINT   DEFAULT 1                 NOT NULL COMMENT '租户ID，用于多租户区分',
    nick_name   VARCHAR(255)                       NOT NULL COMMENT '机器人昵称',
    avatar_url  VARCHAR(255)                       NULL COMMENT '机器人头像URL',
    introduce   TEXT                               NULL COMMENT '机器人介绍',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time DATETIME                           NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
)
    COMMENT '机器人信息表';

CREATE TABLE IF NOT EXISTS assistant_chat_message
(
    id                     BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    chat_session_id        BIGINT                                NOT NULL COMMENT '聊天会话ID，关联chat_session表',
    tenant_id              BIGINT      DEFAULT 1                 NOT NULL COMMENT '租户ID，用于多租户区分',
    meeting_id             BIGINT      DEFAULT 0                 NOT NULL COMMENT '会议ID',
    message_from           VARCHAR(64) DEFAULT '1'               NOT NULL COMMENT '说话人id',
    meeting_type           VARCHAR(32) DEFAULT 'AliTingWu'       NOT NULL COMMENT '会议类型',
    message_from_user_name VARCHAR(255)                          NULL COMMENT '发送方名字',
    content_type           TINYINT(2)  DEFAULT 0                 NOT NULL COMMENT '内容类型，0:文本, 1:图片, 2:语音等',
    content                LONGTEXT                              NULL COMMENT '消息内容',
    create_time            DATETIME    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time            DATETIME                              NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    feedback               TINYINT     DEFAULT 0                 NULL COMMENT '用户反馈，0:无反馈，1:正反馈，-1:负反馈'
)
    COMMENT '聊天消息表';

CREATE TABLE IF NOT EXISTS assistant_chat_session
(
    id             BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    tenant_id      BIGINT     DEFAULT 1                 NOT NULL COMMENT '租户ID，用于多租户区分',
    user_id        BIGINT                               NOT NULL COMMENT '客户ID，唯一标识一个客户',
    bot_id         BIGINT                               NOT NULL COMMENT '机器人ID，关联机器人表',
    form_id        BIGINT                               NULL COMMENT '表单ID',
    mobile         VARCHAR(20)                          NULL COMMENT '手机号',
    user_name      VARCHAR(255)                         NULL COMMENT '客户名称，唯一标识一个客户',
    session_status TINYINT(2) DEFAULT 0                 NOT NULL COMMENT '会话状态，WAIT(0), GOING(1), FINISHED(2)',
    start_time     DATETIME                             NULL COMMENT '开始时间',
    end_time       DATETIME                             NULL COMMENT '结束时间',
    create_time    DATETIME   DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time    DATETIME                             NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
)
    COMMENT '聊天会话表';

CREATE TABLE IF NOT EXISTS assistant_chat_session_extra_data
(
    id              BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    chat_session_id BIGINT                               NOT NULL COMMENT '聊天会话ID，关联chat_session表',
    data_key        VARCHAR(255)                         NOT NULL COMMENT '数据键，用于标识额外数据的类型',
    data_type       TINYINT(2) DEFAULT 0                 NOT NULL COMMENT '数据类型，标识data_value的格式。0：字符串,1：数字,5：jsonobject',
    data_value      LONGTEXT                             NULL COMMENT '数据值，存储具体的额外数据',
    create_time     DATETIME   DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time     DATETIME                             NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    data_version    INT(10)    DEFAULT 0                 NULL COMMENT '版本号',
    CONSTRAINT uk_chat_session_id_data_key_data_version
        UNIQUE (chat_session_id, data_key, data_version) COMMENT '联合唯一约束，确保同一个会话下的data_key和data_version唯一'
)
    COMMENT '聊天会话额外数据表';

CREATE TABLE IF NOT EXISTS assistant_tenant_info
(
    id               BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    tenant_id        BIGINT   DEFAULT 1                 NOT NULL COMMENT '租户ID，用于多租户区分',
    company_name     VARCHAR(255)                       NULL COMMENT '公司名称',
    company_business VARCHAR(255)                       NULL COMMENT '公司业务',
    tag_list         VARCHAR(255)                       NULL COMMENT '标签列表',
    create_time      DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time      DATETIME                           NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
)
    COMMENT '租户信息表';

CREATE TABLE IF NOT EXISTS assistant_user_auth
(
    auth_id     BIGINT AUTO_INCREMENT COMMENT '认证ID'
        PRIMARY KEY,
    user_id     BIGINT                             NOT NULL COMMENT '用户ID',
    auth_type   TINYINT                            NOT NULL COMMENT '认证类型',
    open_id     VARCHAR(255)                       NULL COMMENT '开放ID',
    union_id    VARCHAR(255)                       NULL COMMENT '联合ID',
    login_token VARCHAR(255)                       NULL COMMENT '登录令牌',
    expires_in  INT                                NULL COMMENT '过期时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time DATETIME                           NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
)
    COMMENT '用户认证表';

CREATE INDEX idx_open_id
    ON assistant_user_auth (open_id);

CREATE INDEX idx_user_auth_user_id
    ON assistant_user_auth (user_id);

CREATE TABLE IF NOT EXISTS assistant_user_base
(
    id             BIGINT AUTO_INCREMENT COMMENT '主键ID'
        PRIMARY KEY,
    tenant_id      BIGINT                               NOT NULL COMMENT '租户ID',
    bot_id         BIGINT                               NOT NULL COMMENT '机器人ID',
    mobile         VARCHAR(20)                          NULL COMMENT '手机号',
    user_name      VARCHAR(64)                          NULL,
    avatar_url     VARCHAR(1024)                        NULL,
    user_score     TEXT                                 NULL,
    is_customer    TINYINT(1) DEFAULT 1                 NOT NULL,
    is_deleted     TINYINT(1) DEFAULT 0                 NOT NULL COMMENT '是否删除 0-未删除 1-已删除',
    limit_settings TEXT                                 NULL COMMENT '限制设置',
    expired_date   DATETIME                             NULL COMMENT '账号过期时间',
    user_level     VARCHAR(32)                          NULL COMMENT '用户等级',
    channel        VARCHAR(64) DEFAULT 'gaotu'          NULL COMMENT '渠道',
    create_time    DATETIME   DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time    DATETIME                             NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
)
    COMMENT '用户表';

CREATE INDEX idx_mobile
    ON assistant_user_base (mobile);

CREATE INDEX idx_tenant_id
    ON assistant_user_base (tenant_id);

CREATE TABLE IF NOT EXISTS assistant_user_credential
(
    credential_id BIGINT AUTO_INCREMENT COMMENT '凭证ID'
        PRIMARY KEY,
    user_id       BIGINT                             NOT NULL COMMENT '用户ID',
    login_type    TINYINT                            NOT NULL COMMENT '登录类型',
    login_token   VARCHAR(255)                       NULL COMMENT '登录令牌',
    channel       VARCHAR(64) DEFAULT 'gaotu'        NULL COMMENT '渠道',
    identifier    VARCHAR(255)                       NULL COMMENT '标识符',
    password_hash VARCHAR(255)                       NULL COMMENT '密码哈希',
    create_time   DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    update_time   DATETIME                           NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
)
    COMMENT '用户凭证表';

CREATE INDEX idx_identifier
    ON assistant_user_credential (identifier);

CREATE INDEX idx_user_credential_user_id
    ON assistant_user_credential (user_id);

INSERT INTO assistant_bot_info
    (id, tenant_id, nick_name, avatar_url, introduce, create_time)
SELECT 1, 1, '本地测试机器人', '', 'local bot', NOW()
WHERE NOT EXISTS (
    SELECT 1
    FROM assistant_bot_info
    WHERE id = 1
);
