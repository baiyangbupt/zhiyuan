CREATE TABLE IF NOT EXISTS assistant_codex_thread_binding
(
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    tenant_id             BIGINT       NOT NULL,
    chat_session_id       BIGINT       NOT NULL,
    user_id               BIGINT       NOT NULL,
    thread_id             VARCHAR(128) NOT NULL,
    handle_hash           CHAR(64)     NOT NULL,
    allowed_capabilities  VARCHAR(2048) NOT NULL,
    expires_at            DATETIME     NOT NULL,
    revoked_at            DATETIME     NULL,
    create_time           DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time           DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uk_codex_thread_binding_thread UNIQUE (thread_id),
    CONSTRAINT uk_codex_thread_binding_handle UNIQUE (handle_hash)
);

CREATE INDEX idx_codex_thread_binding_session
    ON assistant_codex_thread_binding (tenant_id, chat_session_id, revoked_at, expires_at);
