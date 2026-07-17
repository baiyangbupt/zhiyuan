ALTER TABLE assistant_planning_pending_command
    ADD COLUMN request_digest VARCHAR(64) NULL COMMENT '规范化请求SHA-256' AFTER expected_plan_version;
