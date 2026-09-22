<?php

/**
 * Click-time source resolver. Browser values identify an already verified
 * citation; all display metadata and protected content come from server-owned
 * authorities after fresh authorization.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\SourceReview;

final class SourceReview
{
    public const NO_APPLICABILITY = 'Guideline evidence for physician review; patient applicability was not determined.';

    public function __construct(
        private readonly SourceReviewAuthorizationPort $authorization,
        private readonly CitationAuthorityPort $citations,
        private readonly SourceViewAuthorityPort $views,
    ) {
    }

    /** @param array<string, mixed> $request @return array<string, mixed> */
    public function open(array $request, string $correlationId): array
    {
        $this->validateRequest($request);
        $context = $this->authorization->authorize(
            $request['conversation_id'],
            $request['turn_id'],
            $correlationId
        );
        $citation = $this->citations->find($context, $request['citation_id']);
        if ($citation === null || ($citation['citation_id'] ?? null) !== $request['citation_id']) {
            throw new SourceReviewException('source_unavailable', false, 'The cited source is unavailable.', 404);
        }
        $view = $this->views->resolve($context, $citation);
        if ($view === null) {
            throw new SourceReviewException('source_unavailable', true, 'The cited source is temporarily unavailable.', 503);
        }

        return match ($citation['source_type'] ?? null) {
            'reviewed_document' => $this->reviewedDocument($citation, $view),
            'openemr_record' => $this->openEmrRecord($citation, $view),
            'guideline' => $this->guideline($citation, $view),
            default => throw new SourceReviewException('source_unavailable', false, 'The cited source type is unavailable.'),
        };
    }

    /** @param array<string, mixed> $request */
    private function validateRequest(array $request): void
    {
        $keys = array_keys($request);
        sort($keys);
        if ($keys !== ['citation_id', 'conversation_id', 'turn_id']
            || !is_string($request['conversation_id'] ?? null)
            || preg_match('/^[a-f0-9]{32}$/', $request['conversation_id']) !== 1
            || !is_string($request['turn_id'] ?? null)
            || preg_match('/^[a-f0-9]{16}$/', $request['turn_id']) !== 1
            || !is_string($request['citation_id'] ?? null)
            || preg_match('/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/', $request['citation_id']) !== 1) {
            throw new SourceReviewException('invalid_contract', false, 'The source request is invalid.', 422);
        }
    }

    /** @param array<string, mixed> $citation @param array<string, mixed> $view @return array<string, mixed> */
    private function reviewedDocument(array $citation, array $view): array
    {
        $region = is_array($citation['page_or_section'] ?? null) ? $citation['page_or_section'] : [];
        $value = is_array($citation['quote_or_value'] ?? null) ? $citation['quote_or_value'] : [];
        $page = is_array($view['page'] ?? null) ? $view['page'] : [];
        $evidence = is_array($view['evidence'] ?? null) ? $view['evidence'] : [];
        $box = is_array($region['box'] ?? null) ? $region['box'] : [];
        $pageBytes = $page['bytes'] ?? null;

        $matches = ($view['source_type'] ?? null) === 'reviewed_document'
            && ($view['source_id'] ?? null) === ($citation['source_id'] ?? null)
            && ($view['source_content_sha256'] ?? null) === ($citation['source_content_sha256'] ?? null)
            && ($view['record_id'] ?? null) === ($citation['record_id'] ?? null)
            && ($view['record_version'] ?? null) === ($citation['record_version'] ?? null)
            && in_array($view['record_status'] ?? null, ['active', 'amended'], true)
            && ($view['field_id'] ?? null) === ($citation['field_or_chunk_id'] ?? null)
            && ($view['review_id'] ?? null) === ($citation['review_id'] ?? null)
            && ($view['review_decision'] ?? null) === ($value['review_decision'] ?? null)
            && ($view['reviewed_value'] ?? null) === ($value['reviewed_value'] ?? null)
            && ($evidence['evidence_id'] ?? null) === ($citation['evidence_id'] ?? null)
            && ($evidence['page_number'] ?? null) === ($region['page_number'] ?? null)
            && ($evidence['box'] ?? null) === $box
            && ($evidence['printed_quote'] ?? null) === ($value['printed_quote'] ?? null)
            && ($page['page_number'] ?? null) === ($region['page_number'] ?? null)
            && ($page['rendered_page_sha256'] ?? null) === ($citation['rendered_page_sha256'] ?? null)
            && ($page['ocr_text_sha256'] ?? null) === ($citation['ocr_text_sha256'] ?? null)
            && is_string($pageBytes)
            && hash_equals((string) ($citation['rendered_page_sha256'] ?? ''), hash('sha256', $pageBytes))
            && $this->validBox($box)
            && in_array($page['media_type'] ?? null, ['image/png', 'image/jpeg'], true);
        if (!$matches) {
            throw new SourceReviewException('source_integrity_failed', false, 'The cited source could not be verified.');
        }

        $title = $this->text($citation['title'] ?? null, 160);
        $documentType = $this->text($view['document_type'] ?? null, 80);
        $fieldId = $this->text($view['field_id'] ?? null, 128);
        $printed = $this->text($value['printed_quote'] ?? null, 500);
        if ($title === null || $documentType === null || $fieldId === null || $printed === null) {
            throw new SourceReviewException('source_integrity_failed', false, 'The cited source could not be verified.');
        }

        return [
            'status' => 'available',
            'lane' => 'patient_record',
            'announcement' => $title . ', reviewed document, version ' . $view['record_version']
                . ', page ' . $page['page_number'] . ', field ' . $fieldId,
            'source' => [
                'source_type' => 'reviewed_document',
                'title' => $title,
                'document_type' => $documentType,
                'record_version' => $view['record_version'],
                'field_id' => $fieldId,
                'review_decision' => $view['review_decision'],
                'reviewed' => ['label' => 'Reviewed', 'value' => $view['reviewed_value']],
                'printed' => ['label' => 'Printed', 'value' => $printed],
                'page_number' => $page['page_number'],
                'box' => $box,
                'focus_label' => 'Cited evidence region',
                'page' => [
                    'media_type' => $page['media_type'],
                    'data_base64' => base64_encode($pageBytes),
                ],
            ],
        ];
    }

    /** @param array<string, mixed> $citation @param array<string, mixed> $view @return array<string, mixed> */
    private function openEmrRecord(array $citation, array $view): array
    {
        $section = is_array($citation['page_or_section'] ?? null) ? $citation['page_or_section'] : [];
        $quoted = is_array($citation['quote_or_value'] ?? null) ? $citation['quote_or_value'] : [];
        $href = $view['href'] ?? null;
        $matches = ($view['source_type'] ?? null) === 'openemr_record'
            && ($view['source_id'] ?? null) === ($citation['source_id'] ?? null)
            && ($view['chart_section'] ?? null) === ($section['section'] ?? null)
            && ($view['record_label'] ?? null) === ($citation['title'] ?? null)
            && ($view['source_version'] ?? null) === ($citation['source_version'] ?? null)
            && ($view['field_id'] ?? null) === ($citation['field_or_chunk_id'] ?? null)
            && ($view['displayed_value'] ?? null) === ($quoted['value'] ?? null)
            && $href === ($citation['href'] ?? null)
            && $this->validSameChartHref($href);
        if (!$matches) {
            throw new SourceReviewException('source_integrity_failed', false, 'The patient-record source could not be verified.');
        }

        $title = $this->text($view['record_label'] ?? null, 160);
        $chartSection = $this->text($view['chart_section'] ?? null, 64);
        $fieldId = $this->text($view['field_id'] ?? null, 64);
        $displayedValue = $this->text($view['displayed_value'] ?? null, 500);
        if ($title === null || $chartSection === null || $fieldId === null || $displayedValue === null) {
            throw new SourceReviewException('source_integrity_failed', false, 'The patient-record source could not be verified.');
        }

        return [
            'status' => 'available',
            'lane' => 'patient_record',
            'announcement' => $title . ', patient record, ' . $chartSection,
            'source' => [
                'source_type' => 'openemr_record',
                'title' => $title,
                'chart_section' => $chartSection,
                'field_id' => $fieldId,
                'source_version' => $view['source_version'],
                'displayed_value' => $displayedValue,
                'same_chart_href' => $href,
            ],
        ];
    }

    /** @param array<string, mixed> $citation @param array<string, mixed> $view @return array<string, mixed> */
    private function guideline(array $citation, array $view): array
    {
        $section = is_array($citation['page_or_section'] ?? null) ? $citation['page_or_section'] : [];
        $quoted = is_array($citation['quote_or_value'] ?? null) ? $citation['quote_or_value'] : [];
        $exactText = $view['exact_text'] ?? null;
        $quote = $quoted['quote'] ?? null;
        $canonicalUrl = $view['canonical_url'] ?? null;
        $matches = ($view['source_type'] ?? null) === 'guideline'
            && ($view['status'] ?? null) === 'active'
            && ($view['source_id'] ?? null) === ($citation['source_id'] ?? null)
            && ($view['corpus_version'] ?? null) === ($citation['corpus_version'] ?? null)
            && ($view['active_corpus_version'] ?? null) === ($citation['corpus_version'] ?? null)
            && ($view['chunk_id'] ?? null) === ($citation['field_or_chunk_id'] ?? null)
            && ($view['publisher'] ?? null) === ($citation['publisher'] ?? null)
            && ($view['title'] ?? null) === ($citation['title'] ?? null)
            && ($view['section_path'] ?? null) === ($section['section_path'] ?? null)
            && ($view['chunk_ordinal'] ?? null) === ($section['chunk_ordinal'] ?? null)
            && ($view['source_sha256'] ?? null) === ($citation['source_sha256'] ?? null)
            && ($view['chunk_sha256'] ?? null) === ($citation['chunk_sha256'] ?? null)
            && $canonicalUrl === ($citation['canonical_url'] ?? null)
            && is_string($exactText)
            && is_string($quote)
            && $quote !== ''
            && str_contains($exactText, $quote)
            && hash_equals((string) ($citation['chunk_sha256'] ?? ''), hash('sha256', $exactText))
            && is_string($canonicalUrl)
            && filter_var($canonicalUrl, FILTER_VALIDATE_URL) !== false
            && str_starts_with($canonicalUrl, 'https://');
        if (!$matches) {
            throw new SourceReviewException('guideline_stale', false, 'The guideline evidence could not be verified.');
        }

        $publisher = $this->text($view['publisher'] ?? null, 160);
        $title = $this->text($view['title'] ?? null, 300);
        $sectionPath = $view['section_path'] ?? null;
        if ($publisher === null || $title === null || !$this->validSectionPath($sectionPath)) {
            throw new SourceReviewException('source_integrity_failed', false, 'The guideline evidence could not be verified.');
        }

        return [
            'status' => 'available',
            'lane' => 'guideline_evidence',
            'announcement' => $title . ', guideline evidence, ' . implode(', ', $sectionPath),
            'source' => [
                'source_type' => 'guideline',
                'publisher' => $publisher,
                'title' => $title,
                'section_path' => $sectionPath,
                'corpus_version' => $view['corpus_version'],
                'exact_excerpt' => $quote,
                'canonical_url' => $canonicalUrl,
                'boundary' => self::NO_APPLICABILITY,
            ],
        ];
    }

    /** @param array<string, mixed> $box */
    private function validBox(array $box): bool
    {
        if (array_keys($box) !== ['x', 'y', 'width', 'height']) {
            return false;
        }
        foreach ($box as $number) {
            if (!is_float($number) && !is_int($number)) {
                return false;
            }
            if ($number < 0 || $number > 1) {
                return false;
            }
        }
        return $box['width'] > 0 && $box['height'] > 0
            && $box['x'] + $box['width'] <= 1
            && $box['y'] + $box['height'] <= 1;
    }

    private function text(mixed $value, int $maximum): ?string
    {
        return is_string($value) && $value !== '' && strlen($value) <= $maximum ? $value : null;
    }

    private function validSectionPath(mixed $value): bool
    {
        if (!is_array($value) || $value === [] || count($value) > 8) {
            return false;
        }
        foreach ($value as $part) {
            if ($this->text($part, 200) === null) {
                return false;
            }
        }
        return true;
    }

    private function validSameChartHref(mixed $value): bool
    {
        return is_string($value)
            && strlen($value) <= 1_000
            && str_starts_with($value, '/')
            && !str_starts_with($value, '//')
            && !str_contains($value, '#')
            && preg_match('/[\x00-\x1f\x7f]/', $value) !== 1;
    }
}
