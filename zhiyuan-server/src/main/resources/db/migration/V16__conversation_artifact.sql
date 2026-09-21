CREATE TABLE IF NOT EXISTS assistant_conversation_artifact
(
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    artifact_id       VARCHAR(64)   NOT NULL,
    tenant_id         BIGINT        NOT NULL,
    chat_session_id   BIGINT        NOT NULL,
    kind              VARCHAR(32)   NOT NULL,
    payload_json      MEDIUMTEXT    NOT NULL,
    payload_digest    CHAR(64)      NOT NULL,
    dependencies_json TEXT          NOT NULL,
    expires_at        DATETIME      NOT NULL,
    create_time       DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time       DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uk_conversation_artifact_id UNIQUE (artifact_id)
);

CREATE INDEX idx_conversation_artifact_scope
    ON assistant_conversation_artifact (tenant_id, chat_session_id, create_time);
