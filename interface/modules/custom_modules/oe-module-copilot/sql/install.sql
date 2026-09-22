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

-- Source-document metadata only. Native OpenEMR owns the encrypted bytes in
-- `documents`; this mapping adds the patient-bound retry and immutable-source
-- seam needed by the Week 2 lab upload. It contains no filename or content.
CREATE TABLE IF NOT EXISTS `copilot_source_upload_intent` (
    `id` CHAR(32) NOT NULL,
    `site_id` VARCHAR(64) NOT NULL,
    `user_id` INT(11) NOT NULL,
    `pid` BIGINT(20) NOT NULL,
    `document_type` VARCHAR(32) NOT NULL,
    `state` VARCHAR(16) NOT NULL,
    `source_id` VARCHAR(48) NULL,
    `created_at` DATETIME NOT NULL,
    `completed_at` DATETIME NULL,
    `expires_at` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_source_intent_scope` (`site_id`, `user_id`, `pid`, `state`),
    UNIQUE KEY `uq_source_intent_source` (`source_id`)
) ENGINE=InnoDB COMMENT='Co-pilot server-bound source upload intents (identifiers only)';

CREATE TABLE IF NOT EXISTS `copilot_source_document` (
    `source_id` VARCHAR(48) NOT NULL,
    `site_id` VARCHAR(64) NOT NULL,
    `pid` BIGINT(20) NOT NULL,
    `native_document_id` BIGINT(20) NOT NULL,
    `native_document_uuid` CHAR(36) NOT NULL,
    `content_hash` CHAR(128) NOT NULL,
    `document_type` VARCHAR(32) NOT NULL,
    `mime_type` VARCHAR(64) NOT NULL,
    `byte_size` INT(11) NOT NULL,
    `page_count` SMALLINT NOT NULL,
    `version` SMALLINT NOT NULL,
    `created_at` DATETIME NOT NULL,
    PRIMARY KEY (`source_id`),
    UNIQUE KEY `uq_source_native_document` (`native_document_id`),
    KEY `idx_source_patient` (`site_id`, `pid`)
) ENGINE=InnoDB COMMENT='Co-pilot immutable source-document identities (no content)';

-- A module-owned category keeps source access behind the same patients|docs
-- ACL as the OpenEMR document route. The category is created only once.
INSERT INTO `categories` (`id`, `name`, `value`, `parent`, `lft`, `rght`, `aco_spec`)
SELECT (SELECT MAX(id) FROM categories) + 1, 'AgentForge Lab Uploads', '', 1, rght, rght + 1, 'patients|docs'
FROM categories
WHERE name = 'Categories'
  AND NOT EXISTS (SELECT 1 FROM categories WHERE name = 'AgentForge Lab Uploads' AND aco_spec = 'patients|docs');
