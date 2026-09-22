<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

use OpenEMR\Modules\Copilot\Documents\LabPdfPolicy;
use OpenEMR\Modules\Copilot\Documents\SourceUploadException;
use PHPUnit\Framework\TestCase;

final class LabPdfPolicyTest extends TestCase
{
    public static function setUpBeforeClass(): void
    {
        require_once dirname(__DIR__) . '/src/Documents/SourceUploadException.php';
        require_once dirname(__DIR__) . '/src/Documents/LabPdfPolicy.php';
    }

    public function testAcceptsOneSyntheticPdfPage(): void
    {
        $pdf = "%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n";
        $result = LabPdfPolicy::validateBytes($pdf, 'application/pdf');

        self::assertSame(1, $result['page_count']);
        self::assertSame(hash('sha3-512', $pdf), $result['content_hash']);
    }

    public function testRejectsWrongMimeMalformedBytesAndTooManyPages(): void
    {
        $pdf = "%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n";
        foreach ([
            ['not a pdf', 'application/pdf'],
            [$pdf, 'text/plain'],
            ['%PDF-1.4' . str_repeat(' /Type /Page', LabPdfPolicy::MAX_PAGES + 1), 'application/pdf'],
        ] as [$bytes, $mime]) {
            try {
                LabPdfPolicy::validateBytes($bytes, $mime);
                self::fail('Expected the file policy to fail closed.');
            } catch (SourceUploadException) {
                self::addToAssertionCount(1);
            }
        }
    }
}
