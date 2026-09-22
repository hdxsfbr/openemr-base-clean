-- Add the internal extraction worker's durable lease and replay protection.
-- Idempotent so an interrupted Module Manager upgrade can be retried.
CREATE TABLE IF NOT EXISTS `copilot_extraction_job` (
    `job_id` CHAR(36) NOT NULL,
    `source_document_id` CHAR(36) NOT NULL,
    `extraction_version` INT UNSIGNED NOT NULL,
    `handoff_id` CHAR(36) NOT NULL,
    `correlation_id` VARCHAR(64) NOT NULL,
    `status` ENUM('queued','leased','completed','failed','canceled') NOT NULL DEFAULT 'queued',
    `attempt` SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    `worker_id` VARCHAR(64) NULL,
    `lease_token_hash` CHAR(64) NULL,
    `lease_expires_at` DATETIME NULL,
    `completion_sha256` CHAR(64) NULL,
    `terminal_sha256` CHAR(64) NULL,
    `extraction_id` CHAR(36) NULL,
    `limitation_code` VARCHAR(64) NULL,
    `retryable` TINYINT(1) NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `claimed_at` DATETIME NULL,
    `completed_at` DATETIME NULL,
    PRIMARY KEY (`job_id`),
    UNIQUE KEY `uq_extraction_job_source_version` (`source_document_id`,`extraction_version`),
    UNIQUE KEY `uq_extraction_job_handoff` (`handoff_id`),
    UNIQUE KEY `uq_extraction_job_result` (`extraction_id`),
    KEY `idx_extraction_job_claim` (`status`,`lease_expires_at`,`created_at`)
) ENGINE=InnoDB COMMENT='Durable leased jobs for the internal extraction worker';

CREATE TABLE IF NOT EXISTS `copilot_worker_nonce` (
    `nonce` CHAR(32) NOT NULL,
    `expires_at` DATETIME NOT NULL,
    PRIMARY KEY (`nonce`),
    KEY `idx_worker_nonce_expiry` (`expires_at`)
) ENGINE=InnoDB COMMENT='Single-use extraction worker request nonces';
