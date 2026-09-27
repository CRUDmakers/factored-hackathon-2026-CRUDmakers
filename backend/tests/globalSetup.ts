import { execSync } from 'node:child_process';

/**
 * Aplica as migrações do Prisma no banco de testes. Os dados são recarregados
 * pelas próprias suítes (resetData), que fazem TRUNCATE antes de carregar as fixtures.
 */
export default function setup() {
  const url = process.env.TEST_DATABASE_URL ?? 'postgresql://banking:banking@localhost:5432/banking_test';
  // Proteção: a suíte apaga dados, então só roda contra bancos *_test.
  if (!new URL(url).pathname.endsWith('_test')) {
    throw new Error(`Recusando rodar testes contra ${url}: o nome do banco precisa terminar em _test.`);
  }
  execSync('npx prisma migrate deploy', { env: { ...process.env, DATABASE_URL: url }, stdio: 'inherit' });
}
