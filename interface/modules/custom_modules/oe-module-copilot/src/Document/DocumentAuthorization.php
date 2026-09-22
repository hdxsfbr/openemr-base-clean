<?php

/**
 * Live operation policy for Week 2 document actions. The policy is evaluated
 * on every call; callers cannot cache its result across requests.
 *
 * @package OpenEMR
 * @license https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document;

final class DocumentAuthorization implements AuthorizationPort
{
    /** @var array<string, list<string>> */
    private const PRINCIPALS = [
        'upload' => ['browser'],
        'source_read' => ['browser', 'worker'],
        'review' => ['browser'],
        'promotion' => ['browser'],
        'amendment' => ['browser'],
        'withdrawal' => ['browser'],
    ];
    private const REVIEW_OPERATIONS = ['review', 'promotion', 'amendment', 'withdrawal'];
    private const TARGET_WRITE_OPERATIONS = ['promotion', 'amendment', 'withdrawal'];

    public function __construct(
        private readonly AccessSnapshotPort $access,
        private readonly AuditPort $audit,
    ) {
    }

    public function authorize(string $operation, string $correlationId): DocumentContext
    {
        $snapshot = $this->access->current();
        $reason = null;
        if (!array_key_exists($operation, self::PRINCIPALS)) {
            $reason = 'wrong_operation';
        } elseif (!$snapshot->active) {
            $reason = 'inactive_user';
        } elseif ($snapshot->breakGlass) {
            $reason = 'breakglass';
        } elseif (!$snapshot->squadAllowed) {
            $reason = 'squad';
        } elseif (!$snapshot->docsAcl) {
            $reason = 'acl';
        } elseif (!in_array($snapshot->principal, self::PRINCIPALS[$operation], true)) {
            $reason = 'principal';
        } elseif (in_array($operation, self::REVIEW_OPERATIONS, true) && !$snapshot->reviewAcl) {
            $reason = 'review_acl';
        } elseif (in_array($operation, self::TARGET_WRITE_OPERATIONS, true) && !$snapshot->targetWriteAcl) {
            $reason = 'target_write_acl';
        }

        if ($reason !== null) {
            try {
                $this->audit->record($snapshot->context, $operation, false, $reason, [
                    'correlation_id' => $correlationId,
                ]);
            } catch (\Throwable $exception) {
                throw new DocumentLifecycleException('unavailable', true, 'The authorization denial could not be audited.', 503);
            }
            throw new DocumentLifecycleException('forbidden', false, 'The document action is not authorized.', 403);
        }
        return $snapshot->context;
    }
}
