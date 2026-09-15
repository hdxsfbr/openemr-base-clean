<?php

/**
 * Clinical date normalization (DQ-HIGH-004, DQ-MEDIUM-006): every date carries
 * its precision and basis; zero-dates and NULLs become "unknown".
 *
/**
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Andre Batista
 * @copyright Copyright (c) 2026 Andre Batista
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Gateway;

final class Dates
{
    /** @return array{value: string|null, precision: string, basis: string} */
    public static function clinical(mixed $value, string $basis = 'clinical'): array
    {
        return self::normalize($value, $basis);
    }

    /** @return array{value: string|null, precision: string, basis: string} */
    public static function unknown(): array
    {
        return ['value' => null, 'precision' => 'unknown', 'basis' => 'unknown'];
    }

    public static function isKnown(array $date): bool
    {
        return $date['value'] !== null && $date['precision'] !== 'unknown';
    }

    /** Date-only string (Y-m-d) for window comparisons, or null. */
    public static function day(array $date): ?string
    {
        return $date['value'] === null ? null : substr($date['value'], 0, 10);
    }

    /** @return array{value: string|null, precision: string, basis: string} */
    private static function normalize(mixed $value, string $basis): array
    {
        if (!is_string($value) || $value === '' || str_starts_with($value, '0000-00-00')) {
            return self::unknown();
        }
        if (preg_match('/^\d{4}-\d{2}-\d{2}$/', $value)) {
            return ['value' => $value, 'precision' => 'day', 'basis' => $basis];
        }
        if (preg_match('/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$/', $value)) {
            return ['value' => str_replace(' ', 'T', substr($value, 0, 19)), 'precision' => 'datetime', 'basis' => $basis];
        }
        return self::unknown();
    }

    public static function inWindow(array $date, ?string $since, ?string $until): bool
    {
        $day = self::day($date);
        if ($day === null) {
            return true; // undated rows are returned and flagged, never silently dropped
        }
        if ($since !== null && $day < $since) {
            return false;
        }
        return !($until !== null && $day > $until);
    }
}
