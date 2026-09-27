import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildApp } from '../src/app.js';
import { prisma } from '../src/db/prisma.js';
import { loadData } from '../src/etl/load.js';

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

export const BARCODE = '23793381286000000000000000000000000000000000'; // 44 dígitos
