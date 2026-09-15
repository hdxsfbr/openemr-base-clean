<?php

/**
 * Clinical notes (the Clinical Notes encounter form). Text is capped, authors
 * may be unknown (DQ-MEDIUM-008), and a bounded term search serves UC-03.
 * Other encounter form types are not covered and are reported as such.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway\Tools;

use OpenEMR\Modules\Copilot\Gateway\AuthorizedPatientContext;
use OpenEMR\Modules\Copilot\Gateway\Dates;
use OpenEMR\Services\ClinicalNotesService;

final class ClinicalNotesTool extends AbstractTool
{
    public const TEXT_CAP = 4000;

    public function name(): string
    {
        return 'clinical_notes';
    }

    public function version(): string
    {
        return '1.0.0';
    }

    public function sections(): array
    {
        return ['notes'];
    }

    public function limit(): int
    {
        return 20;
    }

    protected function fetch(AuthorizedPatientContext $ctx, array $params): array
    {
        $term = $params['term'] !== null ? mb_strtolower($params['term']) : null;
        $records = [];
        foreach (self::rows((new ClinicalNotesService())->getClinicalNotesForPatient($ctx->pid)) as $row) {
            if (!is_array($row) || (int) ($row['pid'] ?? 0) !== $ctx->pid) {
                continue;
            }
            $date = Dates::clinical($row['date'] ?? $row['encounter_date'] ?? null, 'clinical');
            if (!Dates::inWindow($date, $params['since'], $params['until'])) {
                continue;
            }
            [$text, $truncated] = self::cap($row['description'] ?? '', self::TEXT_CAP);
            $matched = $term === null ? null : str_contains(mb_strtolower((string) ($row['description'] ?? '')), $term);
            if ($term !== null && !$matched) {
                continue;
            }
            $records[] = [
                'source' => self::source('form_clinical_notes', (int) $row['id'], $row['uuid'] ?? null),
                'encounter_id' => isset($row['eid']) ? (int) $row['eid'] : null,
                'date' => $date,
                'note_type' => ($row['clinical_notes_type'] ?? '') !== '' ? (string) $row['clinical_notes_type'] : null,
                'author' => self::person($row['username'] ?? null),
                'text' => $text,
                'truncated' => $truncated,
                'term_matched' => $matched,
            ];
        }
        self::sortByDateDesc($records, 'date');
        return ['records' => $records, 'counts' => ['form_types_covered' => 1]];
    }
}
