<?php

/**
 * Base for gateway tools: the common envelope, status semantics, windowing,
 * row caps, and source references (AUDIT.md section 7.1).
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

abstract class AbstractTool
{
    public const CONTRACT_VERSION = '1.0.0';
    public const DEFAULT_LIMIT = 50;

    abstract public function name(): string;

    abstract public function version(): string;

    /** Section keys from ContextBuilder::SECTIONS this tool needs (all required). */
    abstract public function sections(): array;

    /** Maximum records per call. */
    public function limit(): int
    {
        return self::DEFAULT_LIMIT;
    }

    /**
     * @param array{since: ?string, until: ?string, limit: int, term: ?string, analyte: ?string} $params
     * @return array<string, mixed> records plus optional counts/absence_state, or throws
     */
    abstract protected function fetch(AuthorizedPatientContext $ctx, array $params): array;

    /**
     * @param array{since: ?string, until: ?string, limit: int, term: ?string, analyte: ?string} $params
     * @return array<string, mixed> the ToolResponse envelope
     */
    public function run(AuthorizedPatientContext $ctx, array $params): array
    {
        $start = hrtime(true);
        try {
            $result = $this->fetch($ctx, $params);
            $records = $result['records'];
            $limit = min($params['limit'], $this->limit());
            $omitted = max(0, count($records) - $limit);
            $records = array_slice($records, 0, $limit);
            $status = $result['partial'] ?? false ? 'partial' : (count($records) === 0 && $omitted === 0 ? 'empty' : 'ok');
            return $this->envelope($ctx, $params, $status, $result['reason'] ?? null, $records, $omitted, $result['counts'] ?? [], $result['absence_state'] ?? null, $start);
        } catch (\Throwable $e) {
            // PERF-MED-001: a failed retrieval is "unavailable", never "no records".
            error_log('oe-module-copilot tool ' . $this->name() . ' failed: ' . $e::class);
            return $this->envelope($ctx, $params, 'unavailable', 'service_error', [], 0, [], null, $start);
        }
    }

    /** @return array<string, mixed> */
    public function unavailable(AuthorizedPatientContext $ctx, array $params, string $reason): array
    {
        return $this->envelope($ctx, $params, 'unavailable', $reason, [], 0, [], null, hrtime(true));
    }

    /** @return array<string, mixed> */
    private function envelope(AuthorizedPatientContext $ctx, array $params, string $status, ?string $reason, array $records, int $omitted, array $counts, ?string $absence, int $start): array
    {
        return [
            'tool' => $this->name(),
            'tool_version' => $this->version(),
            'contract_version' => self::CONTRACT_VERSION,
            'status' => $status,
            'reason' => $reason,
            'records' => array_values($records),
            'window' => ['since' => $params['since'], 'until' => $params['until']],
            'truncated' => $omitted > 0,
            'omitted_count' => $omitted,
            'counts' => (object) $counts,
            'absence_state' => $absence,
            'latency_ms' => round((hrtime(true) - $start) / 1e6, 1),
            'correlation_id' => $ctx->correlationId,
        ];
    }

    /** @return array{source_id: string, table: string, id: int, uuid: ?string} */
    protected static function source(string $table, int $id, ?string $uuid = null): array
    {
        return ['source_id' => 'openemr:' . $table . ':' . $id . ($uuid !== null ? ':' . $uuid : ''), 'table' => $table, 'id' => $id, 'uuid' => $uuid];
    }

    /** @return array{username: ?string, display: ?string, unknown: bool} */
    protected static function person(?string $username, ?string $display = null): array
    {
        $unknown = ($username === null || $username === '') && ($display === null || $display === '');
        return ['username' => $username !== '' ? $username : null, 'display' => $display !== '' ? $display : null, 'unknown' => $unknown];
    }

    /** @return list<mixed> */
    protected static function rows(mixed $result): array
    {
        if (is_object($result) && method_exists($result, 'getData')) {
            return array_values($result->getData());
        }
        return is_array($result) ? array_values($result) : [];
    }

    /** Sort newest first by a clinical date array; unknown dates last. */
    protected static function sortByDateDesc(array &$records, string $key): void
    {
        usort($records, static function (array $a, array $b) use ($key): int {
            $da = Dates::day($a[$key]) ?? '';
            $db = Dates::day($b[$key]) ?? '';
            return strcmp($db, $da);
        });
    }

    protected static function cap(?string $text, int $max): array
    {
        $text = (string) $text;
        if (mb_strlen($text) <= $max) {
            return [$text, false];
        }
        return [mb_substr($text, 0, $max), true];
    }
}
