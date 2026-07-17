ALTER TABLE assistant_chat_session_pending_confirmation
    ADD COLUMN claim_token VARCHAR(64) NULL COMMENT '当前执行租约持有者token' AFTER status,
    ADD COLUMN claim_expires_at DATETIME NULL COMMENT '当前执行租约过期时间' AFTER claim_token;

CREATE INDEX idx_pending_confirmation_claim_expiry
    ON assistant_chat_session_pending_confirmation (status, claim_expires_at);
