CREATE TABLE IF NOT EXISTS evidence_ledger
(
    evidence_id       VARCHAR(40) NOT NULL COMMENT 'Java 签发的证据 ID：ev_ + ULID',
    tenant_id         BIGINT      NOT NULL COMMENT '租户 ID',
    chat_session_id   BIGINT      NOT NULL COMMENT '会话 ID',
    thread_id         VARCHAR(64) NULL COMMENT '线程 ID',
    source_system     VARCHAR(64) NOT NULL COMMENT '取数来源，如 gaotu.schoolMajorScoreLine',
    params_digest     CHAR(32)    NOT NULL COMMENT '查询参数规范化后的 SHA-256 前 32 位十六进制',
    data_version      VARCHAR(64) NOT NULL COMMENT '签发时观察到的上游数据版本，缺失则不签发',
    algorithm_version VARCHAR(64) NULL COMMENT '算法版本',
    admission_mode    VARCHAR(32) NULL COMMENT '招生口径',
    admission_unit_id VARCHAR(64) NULL COMMENT '招生单元 ID',
    group_code        VARCHAR(32) NULL COMMENT '专业组代码',
    state_version     INT         NULL COMMENT '签发时的状态版本',
    scope_json        JSON        NULL COMMENT '签发范围',
    limitations_json  JSON        NULL COMMENT '限制说明',
    observed_at       DATETIME    NOT NULL COMMENT '取数时间',
    expires_at        DATETIME    NOT NULL COMMENT '新鲜度上限',
    PRIMARY KEY (evidence_id)
);

CREATE INDEX idx_evidence_ledger_session
    ON evidence_ledger (tenant_id, chat_session_id);

CREATE INDEX idx_evidence_ledger_lookup
    ON evidence_ledger (chat_session_id, source_system, params_digest);

CREATE INDEX idx_evidence_ledger_expires
    ON evidence_ledger (expires_at);

CREATE TABLE IF NOT EXISTS evidence_source_version
(
    source_system VARCHAR(64) NOT NULL COMMENT '取数来源',
    data_version  VARCHAR(64) NOT NULL COMMENT '最近一次观察到的上游数据版本',
    observed_at   DATETIME    NOT NULL COMMENT '最近一次观察到该版本的时间',
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (source_system)
);
