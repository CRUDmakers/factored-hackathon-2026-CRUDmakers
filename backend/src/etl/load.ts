/**
 * Carga dos CSVs do datathon no Postgres via COPY (o Prisma não faz carga em massa,
 * então usamos o mesmo pool `pg` que alimenta o adapter do Prisma).
 */
import { createReadStream, existsSync } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { from as copyFrom } from 'pg-copy-streams';
import { pool, prisma } from '../db/prisma.js';

const DIMENSIONS = ['branches', 'customers', 'products', 'daily_exchange_rates'] as const;
/** Colunas dos CSVs de transações (a tabela tem colunas extras para as operações simuladas). */
const TRANSACTION_COLUMNS = [
  'transaction_id', 'transaction_date', 'process_date', 'product_id', 'customer_id',
  'transaction_type', 'transaction_category', 'amount', 'currency', 'amount_usd', 'channel',
  'branch_id', 'merchant_name', 'merchant_category', 'transaction_country', 'transaction_city',
  'transaction_status', 'response_code', 'is_fraud', 'fraud_score', 'latitude', 'longitude',
];

export interface LoadOptions {
  dataDir: string;
  force?: boolean;
  concurrency?: number;
  log?: (message: string) => void;
}

export interface LoadResult {
  skipped: boolean;
  customers: number;
  products: number;
  transactions: number;
}

async function listCsvFiles(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  return entries
    .filter((e) => e.isFile() && e.name.endsWith('.csv'))
    .map((e) => path.join(e.parentPath, e.name))
    .sort();
}

async function copyCsv(table: string, file: string, columns?: string[]): Promise<void> {
  const client = await pool.connect();
  try {
    const cols = columns ? ` (${columns.join(', ')})` : '';
    // HEADER descarta a primeira linha, que é onde fica o BOM dos arquivos.
    const stream = client.query(copyFrom(`COPY ${table}${cols} FROM STDIN WITH (FORMAT csv, HEADER true)`));
    await pipeline(createReadStream(file), stream);
  } finally {
    client.release();
  }
}

async function counts(): Promise<Omit<LoadResult, 'skipped'>> {
  const [customers, products, transactions] = await Promise.all([
    prisma.customer.count(),
    prisma.product.count(),
    prisma.transaction.count(),
  ]);
  return { customers, products, transactions };
}

export async function loadData({ dataDir, force = false, concurrency = 4, log = console.log }: LoadOptions): Promise<LoadResult> {
  const dir = path.resolve(dataDir);
  if (!existsSync(path.join(dir, 'customers.csv'))) {
    throw new Error(`CSVs não encontrados em ${dir}. Ajuste DATA_DIR.`);
  }

  const historical = await prisma.transaction.count({ where: { origin: 'historical' }, take: 1 });
  if (historical > 0 && !force) {
    log('Dados já carregados. Use --force para recarregar.');
    return { skipped: true, ...(await counts()) };
  }

  log(`Carregando dados de ${dir}`);
  await prisma.$executeRawUnsafe(`TRUNCATE ${[...DIMENSIONS, 'transactions', 'scheduled_payments'].join(', ')}`);

  for (const table of DIMENSIONS) {
    await copyCsv(table, path.join(dir, `${table}.csv`));
    log(`  ${table}: ok`);
  }

  const files = await listCsvFiles(path.join(dir, 'transactions'));
  const queue = [...files];
  let done = 0;
  await Promise.all(
    Array.from({ length: concurrency }, async () => {
      for (let file = queue.shift(); file; file = queue.shift()) {
        await copyCsv('transactions', file, TRANSACTION_COLUMNS);
        done += 1;
        if (done % 100 === 0 || done === files.length) log(`  transactions: ${done}/${files.length} arquivos`);
      }
    }),
  );

  // O dataset mistura "Mexico" e "México".
  await prisma.transaction.updateMany({ where: { transaction_country: 'Mexico' }, data: { transaction_country: 'México' } });
  await prisma.$executeRawUnsafe('ANALYZE');

  const result = { skipped: false, ...(await counts()) };
  log(`Carga concluída: ${JSON.stringify(result)}`);
  return result;
}
