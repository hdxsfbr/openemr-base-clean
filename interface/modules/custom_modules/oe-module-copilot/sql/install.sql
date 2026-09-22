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

-- One row owns both the server-issued upload intent and its immutable mapping
-- to OpenEMR's encrypted Document store. No document bytes live here.
CREATE TABLE IF NOT EXISTS `copilot_document_upload` (
    `upload_intent_id` CHAR(36) NOT NULL,
    `site_id` VARCHAR(64) NOT NULL,
    `pid` BIGINT(20) NOT NULL,
    `user_id` INT(11) NOT NULL,
    `category` ENUM('lab_report','intake_form') NOT NULL,
    `upload_request_idempotency_key` CHAR(36) NOT NULL,
    `original_filename` VARCHAR(255) NOT NULL,
    `declared_mime_type` VARCHAR(64) NOT NULL,
    `declared_byte_count` INT UNSIGNED NOT NULL,
    `declared_page_count` SMALLINT UNSIGNED NOT NULL,
    `token_hash` CHAR(64) NOT NULL,
    `expires_at` DATETIME NOT NULL,
    `source_document_id` CHAR(36) NULL,
    `openemr_document_id` VARCHAR(128) NULL,
    `content_sha256` CHAR(64) NULL,
    `actual_byte_count` INT UNSIGNED NULL,
    `actual_mime_type` VARCHAR(64) NULL,
    `actual_page_count` SMALLINT UNSIGNED NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `completed_at` DATETIME NULL,
    PRIMARY KEY (`upload_intent_id`),
    UNIQUE KEY `uq_upload_request` (`site_id`,`pid`,`category`,`upload_request_idempotency_key`),
    UNIQUE KEY `uq_upload_mapping` (`site_id`,`pid`,`category`,`upload_intent_id`),
    UNIQUE KEY `uq_source_document` (`source_document_id`),
    UNIQUE KEY `uq_openemr_document` (`openemr_document_id`),
    KEY `idx_patient_content` (`site_id`,`pid`,`content_sha256`),
    KEY `idx_upload_expiry` (`expires_at`)
) ENGINE=InnoDB COMMENT='Immutable co-pilot source mappings; OpenEMR Document owns bytes';

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

CREATE TABLE IF NOT EXISTS `copilot_document_extraction` (
    `extraction_id` CHAR(36) NOT NULL,
    `source_document_id` CHAR(36) NOT NULL,
    `extraction_version` INT UNSIGNED NOT NULL,
    `schema_name` VARCHAR(64) NOT NULL,
    `schema_version` VARCHAR(32) NOT NULL,
    `state` ENUM('schema_valid','review_required','rejected','unavailable') NOT NULL,
    `extraction_json` LONGTEXT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`extraction_id`),
    UNIQUE KEY `uq_source_extraction_version` (`source_document_id`,`extraction_version`),
    CONSTRAINT `chk_extraction_json` CHECK (JSON_VALID(`extraction_json`))
) ENGINE=InnoDB COMMENT='Immutable schema-valid document extraction versions';

CREATE TABLE IF NOT EXISTS `copilot_proposed_fact` (
    `extraction_id` CHAR(36) NOT NULL,
    `field_id` VARCHAR(128) NOT NULL,
    `typed_value_json` LONGTEXT NULL,
    `evidence_json` LONGTEXT NOT NULL,
    `state` ENUM('schema_valid','review_required','rejected','unavailable') NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`extraction_id`,`field_id`),
    CONSTRAINT `chk_proposed_value_json` CHECK (`typed_value_json` IS NULL OR JSON_VALID(`typed_value_json`)),
    CONSTRAINT `chk_proposed_evidence_json` CHECK (JSON_VALID(`evidence_json`))
) ENGINE=InnoDB COMMENT='Immutable proposed facts and source evidence';

CREATE TABLE IF NOT EXISTS `copilot_fact_review` (
    `review_id` CHAR(36) NOT NULL,
    `review_idempotency_key` CHAR(36) NOT NULL,
    `extraction_id` CHAR(36) NOT NULL,
    `extraction_version` INT UNSIGNED NOT NULL,
    `field_id` VARCHAR(128) NOT NULL,
    `decision` ENUM('approved','corrected','rejected') NOT NULL,
    `review_json` LONGTEXT NOT NULL,
    `supersedes_review_id` CHAR(36) NULL,
    `reviewed_by` VARCHAR(128) NOT NULL,
    `reviewed_at` DATETIME NOT NULL,
    PRIMARY KEY (`review_id`),
    UNIQUE KEY `uq_review_idempotency` (`review_idempotency_key`),
    KEY `idx_review_fact_current` (`extraction_id`,`field_id`,`supersedes_review_id`),
    CONSTRAINT `chk_review_json` CHECK (JSON_VALID(`review_json`))
) ENGINE=InnoDB COMMENT='Append-only physician fact reviews';

CREATE TABLE IF NOT EXISTS `copilot_promoted_record` (
    `record_id` CHAR(36) NOT NULL,
    `record_version` INT UNSIGNED NOT NULL,
    `target_type` ENUM('lab_report','intake_response') NOT NULL,
    `status` ENUM('active','completed','amended','withdrawn','stopped') NOT NULL,
    `action_id` CHAR(36) NOT NULL,
    `action_idempotency_key` CHAR(36) NOT NULL,
    `deterministic_promotion_key` CHAR(64) NOT NULL,
    `review_set_sha256` CHAR(64) NOT NULL,
    `source_content_sha256` CHAR(64) NOT NULL,
    `source_document_id` CHAR(36) NOT NULL,
    `extraction_id` CHAR(36) NOT NULL,
    `extraction_version` INT UNSIGNED NOT NULL,
    `site_id` VARCHAR(64) NOT NULL,
    `pid` BIGINT(20) NOT NULL,
    `record_json` LONGTEXT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`record_id`,`record_version`),
    UNIQUE KEY `uq_record_action` (`action_id`),
    UNIQUE KEY `uq_record_action_idempotency` (`action_idempotency_key`),
    UNIQUE KEY `uq_promotion_key` (`deterministic_promotion_key`),
    KEY `idx_reviewed_record_current` (`site_id`,`pid`,`record_id`,`record_version`),
    KEY `idx_reviewed_record_source` (`source_document_id`,`extraction_id`,`extraction_version`),
    CONSTRAINT `chk_promoted_record_json` CHECK (JSON_VALID(`record_json`))
) ENGINE=InnoDB COMMENT='Immutable reviewed document record versions';

CREATE TABLE IF NOT EXISTS `copilot_action_outbox` (
    `event_id` CHAR(36) NOT NULL,
    `event_type` VARCHAR(64) NOT NULL,
    `aggregate_id` CHAR(36) NOT NULL,
    `site_id` VARCHAR(64) NOT NULL,
    `pid` BIGINT(20) NOT NULL,
    `user_id` INT(11) NOT NULL,
    `correlation_id` VARCHAR(64) NOT NULL,
    `payload_json` LONGTEXT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `published_at` DATETIME NULL,
    PRIMARY KEY (`event_id`),
    KEY `idx_outbox_unpublished` (`published_at`,`created_at`),
    CONSTRAINT `chk_outbox_json` CHECK (JSON_VALID(`payload_json`))
) ENGINE=InnoDB COMMENT='Transactional document action audit/provenance outbox';
