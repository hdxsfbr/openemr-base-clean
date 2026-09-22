<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

use OpenEMR\Modules\Copilot\Documents\UploadRequestPolicy;
use PHPUnit\Framework\TestCase;

final class UploadRequestPolicyTest extends TestCase
{
    public static function setUpBeforeClass(): void
    {
        require_once dirname(__DIR__) . '/src/Documents/SourceDocumentRepository.php';
        require_once dirname(__DIR__) . '/src/Documents/UploadRequestPolicy.php';
    }

    public function testIntentRejectsEveryClientPatientSelector(): void
    {
        self::assertTrue(UploadRequestPolicy::acceptsIntent(['document_type' => 'lab_pdf']));
        self::assertFalse(UploadRequestPolicy::acceptsIntent(['document_type' => 'lab_pdf', 'pid' => 2]));
        self::assertFalse(UploadRequestPolicy::acceptsIntent(['document_type' => 'lab_pdf', 'patient_id' => null]));
        self::assertFalse(UploadRequestPolicy::acceptsIntent(['document_type' => 'intake_form']));
    }

    public function testUploadRejectsEveryClientAuthorityField(): void
    {
        self::assertTrue(UploadRequestPolicy::acceptsUpload(['intent_id' => str_repeat('a', 32)]));
        self::assertFalse(UploadRequestPolicy::acceptsUpload(['pid' => 2]));
        self::assertFalse(UploadRequestPolicy::acceptsUpload(['patient_id' => null]));
        self::assertFalse(UploadRequestPolicy::acceptsUpload(['document_type' => 'lab_pdf']));
    }
}
