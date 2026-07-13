CREATE INDEX idx_planning_pending_command_retention
    ON assistant_planning_pending_command (status, update_time, id);
