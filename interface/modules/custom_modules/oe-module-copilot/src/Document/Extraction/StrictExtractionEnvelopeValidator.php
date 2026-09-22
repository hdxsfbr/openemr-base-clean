<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

use Opis\JsonSchema\Validator;

final class StrictExtractionEnvelopeValidator implements ExtractionEnvelopeValidatorPort
{
    public function __construct(private readonly string $schemaDirectory)
    {
    }

    public function validateAndFlatten(array $envelope): array
    {
        $documentType = $envelope['source']['document_type'] ?? null;
        $schemaFile = match ($documentType) {
            'lab_report' => 'lab_extraction.schema.json',
            'intake_form' => 'intake_extraction.schema.json',
            default => null,
        };
        if ($schemaFile === null) {
            throw $this->invalid();
        }
        $schema = @file_get_contents(rtrim($this->schemaDirectory, '/') . '/' . $schemaFile);
        if (!is_string($schema)) {
            throw new ExtractionGatewayException('unavailable', true, 'Extraction schema unavailable.', 503);
        }
        try {
            $schemaValue = $envelope;
            // json_decode(..., true) represents both {} and [] as an empty PHP
            // array. Demographics is the one contract object allowed to be
            // empty, so restore its object shape for JSON Schema validation.
            if ($documentType === 'intake_form' && ($schemaValue['payload']['demographics'] ?? null) === []) {
                $schemaValue['payload']['demographics'] = new \stdClass();
            }
            $encoded = json_encode($schemaValue, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION);
            $result = (new Validator())->validate(json_decode($encoded), json_decode($schema, false, 512, JSON_THROW_ON_ERROR));
        } catch (\JsonException $exception) {
            throw $this->invalid();
        }
        if (!$result->isValid()) {
            throw $this->invalid();
        }

        $source = $envelope['source'];
        $sourceLimitsValid = $source['document_type'] === 'lab_report'
            ? $source['mime_type'] === 'application/pdf'
                && $source['byte_count'] <= 20_971_520 && $source['page_count'] <= 20
            : in_array($source['mime_type'], ['application/pdf', 'image/png', 'image/jpeg'], true)
                && $source['byte_count'] <= 10_485_760 && $source['page_count'] <= 10
                && ($source['mime_type'] === 'application/pdf' || $source['page_count'] === 1);
        if (!$sourceLimitsValid) {
            throw $this->invalid();
        }

        $pages = [];
        foreach ($envelope['ocr_pages'] as $index => $page) {
            $number = $index + 1;
            if (($page['page_number'] ?? null) !== $number
                || !hash_equals((string) $page['text_sha256'], hash('sha256', (string) $page['text']))) {
                throw $this->invalid();
            }
            $pages[$number] = $page;
            $expectedToken = 0;
            $lastEnd = 0;
            foreach ($page['tokens'] as $token) {
                if ($token['token_index'] !== $expectedToken++
                    || $token['span_start'] < $lastEnd
                    || $token['span_end'] > strlen($page['text'])
                    || substr($page['text'], $token['span_start'], $token['span_end'] - $token['span_start']) !== $token['text']) {
                    throw $this->invalid();
                }
                $lastEnd = $token['span_end'];
                $this->assertBox($token['box']);
            }
        }
        if (count($pages) !== (int) $envelope['source']['page_count']) {
            throw $this->invalid();
        }

        $facts = [];
        $ids = [];
        $this->collectFields($envelope['payload'], $pages, $facts, $ids);
        usort($facts, static fn(array $a, array $b): int => strcmp($a['field_id'], $b['field_id']));
        return $facts;
    }

    /**
     * @param mixed $node
     * @param array<int, array<string, mixed>> $pages
     * @param list<array<string, mixed>> $facts
     * @param array<string, true> $ids
     */
    private function collectFields(mixed $node, array $pages, array &$facts, array &$ids): void
    {
        if (!is_array($node)) {
            return;
        }
        if (isset($node['field_id'], $node['state'], $node['evidence']) && array_key_exists('value', $node)) {
            $fieldId = (string) $node['field_id'];
            if (isset($ids[$fieldId])) {
                throw $this->invalid();
            }
            $ids[$fieldId] = true;
            $evidenceCount = count($node['evidence']);
            if (($node['value'] !== null && ($evidenceCount < 1 || $evidenceCount > 3))
                || ($node['value'] === null
                    && (!in_array($node['state'], ['review_required', 'unavailable'], true) || $evidenceCount !== 0))) {
                throw $this->invalid();
            }
            $evidenceIds = [];
            foreach ($node['evidence'] as $evidence) {
                $page = $pages[(int) $evidence['page_number']] ?? null;
                if (isset($evidenceIds[$evidence['evidence_id']])
                    || count(array_unique($evidence['validation'])) !== count($evidence['validation'])
                    || $page === null
                    || $evidence['ocr_span_end'] > strlen($page['text'])
                    || $evidence['ocr_span_start'] >= $evidence['ocr_span_end']
                    || !hash_equals((string) $page['text_sha256'], (string) $evidence['ocr_text_sha256'])
                    || !hash_equals((string) $page['rendered_page_sha256'], (string) $evidence['rendered_page_sha256'])
                    || substr($page['text'], $evidence['ocr_span_start'], $evidence['ocr_span_end'] - $evidence['ocr_span_start']) !== $evidence['printed_quote']) {
                    throw $this->invalid();
                }
                $evidenceIds[$evidence['evidence_id']] = true;
                $this->assertBox($evidence['box']);
            }
            $facts[] = [
                'field_id' => $fieldId,
                'typed_value' => $node['value'],
                'evidence' => $node['evidence'],
                'state' => $node['state'],
            ];
            return;
        }
        foreach ($node as $child) {
            $this->collectFields($child, $pages, $facts, $ids);
        }
    }

    /** @param array<string, mixed> $box */
    private function assertBox(array $box): void
    {
        if ((float) $box['x'] + (float) $box['width'] > 1.0
            || (float) $box['y'] + (float) $box['height'] > 1.0) {
            throw $this->invalid();
        }
    }

    private function invalid(): ExtractionGatewayException
    {
        return new ExtractionGatewayException('invalid_contract', false, 'The extraction envelope is invalid.', 422);
    }
}
