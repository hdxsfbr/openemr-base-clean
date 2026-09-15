<?php

/**
 * The closed set of gateway tools and their parameter validation. No tool
 * accepts a patient identifier; unknown parameters are rejected.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway\Tools;

final class ToolRegistry
{
    /** @return array<string, AbstractTool> */
    public static function all(): array
    {
        $tools = [new PatientContextTool(), new EncountersTool(), new ClinicalNotesTool(), new ProblemsTool(), new MedicationsTool(), new AllergiesTool(), new LabResultsTool()];
        $byName = [];
        foreach ($tools as $tool) {
            $byName[$tool->name()] = $tool;
        }
        return $byName;
    }

    public static function get(string $name): ?AbstractTool
    {
        return self::all()[$name] ?? null;
    }

    /**
     * Validates raw parameters against the contract (contracts/schema/*_params.schema.json).
     * @param array<string, mixed> $raw
     * @return array{since: ?string, until: ?string, limit: int, term: ?string, analyte: ?string}
     * @throws \InvalidArgumentException
     */
    public static function params(AbstractTool $tool, array $raw): array
    {
        $allowed = ['since', 'until', 'limit', 'cursor'];
        if ($tool instanceof ClinicalNotesTool) {
            $allowed[] = 'term';
        }
        if ($tool instanceof LabResultsTool) {
            $allowed[] = 'analyte';
        }
        foreach (array_keys($raw) as $key) {
            if (!in_array($key, $allowed, true)) {
                throw new \InvalidArgumentException('unexpected parameter: ' . (string) $key);
            }
        }
        $date = static function (mixed $v, string $name): ?string {
            if ($v === null || $v === '') {
                return null;
            }
            if (!is_string($v) || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $v) || !checkdate((int) substr($v, 5, 2), (int) substr($v, 8, 2), (int) substr($v, 0, 4))) {
                throw new \InvalidArgumentException('invalid ' . $name);
            }
            return $v;
        };
        $text = static function (mixed $v, string $name): ?string {
            if ($v === null || $v === '') {
                return null;
            }
            if (!is_string($v) || mb_strlen($v) < 2 || mb_strlen($v) > 80) {
                throw new \InvalidArgumentException('invalid ' . $name);
            }
            return $v;
        };
        $limit = $raw['limit'] ?? $tool->limit();
        if (!is_int($limit) || $limit < 1 || $limit > $tool->limit()) {
            throw new \InvalidArgumentException('invalid limit');
        }
        return [
            'since' => $date($raw['since'] ?? null, 'since'),
            'until' => $date($raw['until'] ?? null, 'until'),
            'limit' => $limit,
            'term' => $text($raw['term'] ?? null, 'term'),
            'analyte' => $text($raw['analyte'] ?? null, 'analyte'),
        ];
    }
}
