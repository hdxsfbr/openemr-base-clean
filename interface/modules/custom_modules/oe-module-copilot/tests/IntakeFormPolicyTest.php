<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

use OpenEMR\Modules\Copilot\Documents\IntakeFormPolicy;
use OpenEMR\Modules\Copilot\Documents\SourceUploadException;
use PHPUnit\Framework\TestCase;

final class IntakeFormPolicyTest extends TestCase
{
    public static function setUpBeforeClass(): void
    {
        require_once dirname(__DIR__) . '/src/Documents/SourceUploadException.php';
        require_once dirname(__DIR__) . '/src/Documents/LabPdfPolicy.php';
        require_once dirname(__DIR__) . '/src/Documents/IntakeFormPolicy.php';
    }

    public function testAcceptsTheBoundedSyntheticIntakePdfFormat(): void
    {
        $pdf = "%PDF-1.4\n% AgentForge Synthetic Intake Form\n1 0 obj << /Type /Page >> endobj\n";
        $result = IntakeFormPolicy::validateBytes($pdf, 'application/pdf');

        self::assertSame('intake_form', $result['document_type']);
        self::assertSame(1, $result['page_count']);
    }

    public function testRejectsALabPayloadDeclaredAsAnIntakeForm(): void
    {
        $lab = "%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n";

        $this->expectException(SourceUploadException::class);
        IntakeFormPolicy::validateBytes($lab, 'application/pdf');
    }
}
