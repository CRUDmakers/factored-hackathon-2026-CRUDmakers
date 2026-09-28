import { defineConfig } from 'vitest/config';

const testDatabaseUrl = process.env.TEST_DATABASE_URL ?? 'postgresql://banking:banking@localhost:5432/banking_test';

export default defineConfig({
  test: {
    // Os testes compartilham um único banco, então os arquivos rodam em sequência.
    fileParallelism: false,
    globalSetup: ['tests/globalSetup.ts'],
    setupFiles: ['tests/setup.ts'],
    env: { DATABASE_URL: testDatabaseUrl, LOG_LEVEL: 'silent' },
    testTimeout: 20_000,
    hookTimeout: 60_000,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      // Código gerado pelo Prisma e pontos de entrada que só ligam o processo.
      exclude: ['src/generated/**', 'src/main.ts', 'src/etl/cli.ts'],
      reporter: ['text', 'html'],
      thresholds: { lines: 100, functions: 100, branches: 100, statements: 100 },
    },
  },
});
