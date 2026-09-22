<?php

declare(strict_types=1);

namespace OpenEMR\Modules\Copilot\Tests;

use JsonSchema\Validator;
use PHPUnit\Framework\TestCase;

final class Week2ContractFixtureTest extends TestCase
{
    private const SCHEMA = '/contracts/schema/review_fact_command.schema.json';
    private const FIXTURES = '/contracts/fixtures/week2';

    public function testSharedValidFixtureMatchesExportedSchema(): void
    {
        $validator = $this->validateFixture('review_fact_command.valid.json');
        self::assertTrue($validator->isValid(), json_encode($validator->getErrors(), JSON_THROW_ON_ERROR));
    }

    public function testSharedFixtureWithBrowserSelectedPatientFailsClosed(): void
    {
        $validator = $this->validateFixture('review_fact_command.invalid-extra.json');
        self::assertFalse($validator->isValid());
    }

    private function validateFixture(string $fixtureName): Validator
    {
        $root = dirname(__DIR__, 5);
        $payload = $this->decodeJson($root . self::FIXTURES . '/' . $fixtureName);
        $schema = $this->decodeJson($root . self::SCHEMA);
        $validator = new Validator();
        $validator->validate($payload, $schema);
        return $validator;
    }

    private function decodeJson(string $path): mixed
    {
        $contents = file_get_contents($path);
        if ($contents === false) {
            throw new \RuntimeException('Cannot read ' . $path);
        }
        return json_decode($contents, false, 512, JSON_THROW_ON_ERROR);
    }
}
