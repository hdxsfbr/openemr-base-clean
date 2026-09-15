-- AgentForge Clinical Co-Pilot: conversation binding (ADR-0002, ADR-0005).
-- Holds identifiers only; no clinical values. Rows are closed on logout,
-- patient switch, idle timeout, or panel close, and deleted 24 h after close.
CREATE TABLE IF NOT EXISTS `copilot_conversation` (
    `id` CHAR(32) NOT NULL COMMENT 'Conversation id (random hex)',
    `site_id` VARCHAR(64) NOT NULL,
    `user_id` INT(11) NOT NULL COMMENT 'users.id at binding time',
    `username` VARCHAR(255) NOT NULL COMMENT 'ACLs are keyed by username',
    `pid` BIGINT(20) NOT NULL COMMENT 'Bound patient; never taken from the client',
    `correlation_id` VARCHAR(64) NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `last_turn_at` DATETIME NULL DEFAULT NULL,
    `turn_count` INT(11) NOT NULL DEFAULT 0,
    `closed_at` DATETIME NULL DEFAULT NULL,
    `close_reason` VARCHAR(40) NULL DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_user_pid_open` (`user_id`, `pid`, `closed_at`),
    KEY `idx_closed_at` (`closed_at`)
) ENGINE=InnoDB COMMENT='Co-pilot conversation bindings (identifiers only)';
