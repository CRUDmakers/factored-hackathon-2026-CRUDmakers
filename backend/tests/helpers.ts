import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { InjectOptions } from 'fastify';
import { buildApp } from '../src/app.js';
import { config } from '../src/config.js';
import { prisma } from '../src/db/prisma.js';
import { loadData } from '../src/etl/load.js';
import { SERVICE_KEY_HEADER, signSession } from '../src/services/auth.js';

export const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'data');

export const ANA = 'CLI-ANA000000001';
export const BRUNO = 'CLI-BRUNO0000002';
export const CARLA = 'CLI-CARLA0000003';
export const DIEGO = 'CLI-DIEGO0000004';
export const UNKNOWN = 'CLI-NOPE00000000';

/** Recarrega as fixtures do zero (também apaga operações simuladas e agendamentos). */
export async function resetData() {
  await loadData({ dataDir: FIXTURES, force: true, log: () => {} });
}

export async function balanceOf(productId: string): Promise<number | null> {
  const p = await prisma.product.findUniqueOrThrow({ where: { product_id: productId } });
  return p.current_balance?.toNumber() ?? null;
}

export async function testApp() {
  const app = await buildApp({ logger: false });
  await app.ready();
  return app;
}

/** Header Authorization com uma sessão válida do cliente (`now` no passado gera token expirado). */
export function bearer(customerId: string, now?: number) {
  return { authorization: `Bearer ${signSession(customerId, now).token}` };
}

/** Header da chave de serviço (provedor de identidade de teste / operações internas). */
export const SERVICE = { [SERVICE_KEY_HEADER]: config.authServiceKey };

/**
 * App de teste em que cada requisição a /api/customers/{id}/… já vai autenticada como o dono dos dados
 * (o cliente da URL). As suítes de regra de negócio usam este; os casos de acesso negado estão em auth.test.ts.
 */
export async function ownerApp() {
  const app = await testApp();
  const inject = app.inject.bind(app);
  app.inject = ((opts: string | InjectOptions) => {
    const req = typeof opts === 'string' ? { url: opts } : opts;
    const owner = /^\/api\/customers\/([^/?]+)/.exec(String(req.url))?.[1];
    return inject({ ...req, headers: { ...(owner && bearer(owner)), ...req.headers } });
  }) as typeof app.inject;
  return app;
}

export const BARCODE = '23793381286000000000000000000000000000000000'; // 44 dígitos
