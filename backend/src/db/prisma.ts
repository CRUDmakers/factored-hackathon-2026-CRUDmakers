import { PrismaPg } from '@prisma/adapter-pg';
import pg from 'pg';
import { config } from '../config.js';
import { Prisma, PrismaClient } from '../generated/prisma/client.js';

export { Prisma };
export const Decimal = Prisma.Decimal;
export type Decimal = Prisma.Decimal;

// Na API os valores monetários saem como número JSON, e não como string.
(Prisma.Decimal.prototype as unknown as { toJSON(this: Prisma.Decimal): number }).toJSON = function toJSON() {
  return this.toNumber();
};

/** Pool compartilhado: usado pelo adapter do Prisma e pelo COPY do ETL. */
export const pool = new pg.Pool({ connectionString: config.databaseUrl, max: 10 });
export const prisma = new PrismaClient({ adapter: new PrismaPg(pool) });

export type Db = PrismaClient | Prisma.TransactionClient;

export async function disconnect(): Promise<void> {
  await prisma.$disconnect();
  await pool.end();
}
