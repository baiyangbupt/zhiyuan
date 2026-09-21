CREATE TABLE IF NOT EXISTS assistant_conversation_proposal_request
(
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT       NOT NULL,
    chat_session_id BIGINT       NOT NULL,
    request_id      VARCHAR(64)  NOT NULL,
    request_digest  CHAR(64)     NOT NULL,
    pending_id      VARCHAR(64)  NULL,
    operation_id    VARCHAR(64)  NULL,
    result_json     TEXT         NULL,
    status          VARCHAR(24)  NOT NULL,
    create_time     DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time     DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uk_conversation_proposal_request UNIQUE (tenant_id, chat_session_id, request_id)
);
