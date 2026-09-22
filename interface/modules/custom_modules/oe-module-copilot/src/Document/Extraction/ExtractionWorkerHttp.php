<?php

/** @package OpenEMR @license https://github.com/openemr/openemr/blob/master/LICENSE GNU GPL 3 */

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Document\Extraction;

final class ExtractionWorkerHttp
{
    public function __construct(
        private readonly ExtractionWorkerAuthenticator $authenticator,
        private readonly ExtractionJobGateway $gateway,
    ) {
    }

    /**
     * @param array<string, string> $headers
     * @return array{status: int, body: array<string, mixed>}
     */
    public function handle(
        string $method,
        string $path,
        string $remoteAddress,
        array $headers,
        string $rawBody,
        string $correlationId,
    ): array {
        try {
            if (!$this->isInternalAddress($remoteAddress)) {
                throw new ExtractionGatewayException('unauthorized', false, 'Worker request denied.', 401);
            }
            $this->authenticator->authenticate($headers, $method, $path, $rawBody);
            $request = json_decode($rawBody, true, 64, JSON_THROW_ON_ERROR);
            if (!is_array($request) || !$this->hasExactKeys($request, ['operation', 'command'])
                || !is_string($request['operation']) || !is_array($request['command'])) {
                throw new ExtractionGatewayException('invalid_contract', false, 'The worker request is invalid.', 422);
            }
            $body = match ($request['operation']) {
                'claim' => $this->gateway->claim($request['command']) ?? ['status' => 'idle'],
                'complete' => $this->gateway->complete($request['command']),
                'fail' => $this->gateway->fail($request['command']),
                'cancel' => $this->gateway->cancel($request['command']),
                default => throw new ExtractionGatewayException('invalid_contract', false, 'The worker operation is invalid.', 422),
            };
            return ['status' => 200, 'body' => $body];
        } catch (\JsonException $exception) {
            return $this->error(new ExtractionGatewayException('invalid_contract', false, 'The worker request is invalid.', 422), $correlationId);
        } catch (ExtractionGatewayException $exception) {
            return $this->error($exception, $correlationId);
        } catch (\Throwable $exception) {
            error_log('oe-module-copilot extraction gateway failed: ' . $exception::class);
            return $this->error(new ExtractionGatewayException('unavailable', true, 'The extraction gateway is unavailable.', 503), $correlationId);
        }
    }

    /** @return array{status: int, body: array<string, mixed>} */
    private function error(ExtractionGatewayException $exception, string $correlationId): array
    {
        return ['status' => $exception->httpStatus, 'body' => [
            'code' => $exception->errorCode,
            'correlation_id' => $correlationId,
            'retryable' => $exception->retryable,
            'limitation' => $exception->getMessage(),
        ]];
    }

    /** @param array<string, mixed> $actual @param list<string> $expected */
    private function hasExactKeys(array $actual, array $expected): bool
    {
        $keys = array_keys($actual);
        sort($keys);
        sort($expected);
        return $keys === $expected;
    }

    private function isInternalAddress(string $address): bool
    {
        if ($address === '127.0.0.1' || $address === '::1') {
            return true;
        }
        $packed = @inet_pton($address);
        if ($packed === false) {
            return false;
        }
        if (strlen($packed) === 4) {
            $number = unpack('N', $packed)[1];
            return ($number & 0xff000000) === 0x0a000000
                || ($number & 0xfff00000) === 0xac100000
                || ($number & 0xffff0000) === 0xc0a80000;
        }
        return str_starts_with(bin2hex($packed), 'fc') || str_starts_with(bin2hex($packed), 'fd');
    }
}

