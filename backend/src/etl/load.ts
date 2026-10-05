/**
 * ETL dos CSVs do datathon → Postgres (COPY para uma tabela de staging e INSERT validado no destino).
 *
 * - Contrato de schema: o cabeçalho de cada CSV tem que ser exatamente o esperado, senão a carga para.
 *   Cada valor tem que caber no tipo da coluna de destino (pg_input_is_valid) e seguir as regras de RULES.
 *   Linhas fora do contrato são rejeitadas e contadas por motivo; o resto do arquivo entra.
 *   CSV estruturalmente quebrado (colunas a mais, aspas abertas) aborta o arquivo inteiro, sem carga parcial.
 * - Linhagem: cada arquivo carregado gera um registro em etl_files (caminho, sha256, linhas lidas, carregadas
 *   e rejeitadas, motivos, horário), e cada transação guarda o arquivo de origem em transactions.source_file.
 * - Incremental: um arquivo só é (re)carregado quando o sha256 muda. As transações vêm particionadas por dia
 *   de processamento (transactions/year=/month=/day=, process_date); recarregar uma partição troca só as
 *   linhas daquele arquivo. Dimensões são snapshots: se o arquivo mudou, a tabela é substituída.
 * - Atualidade: a partição D deve chegar até D+1; se a última partição carregada for mais antiga, a carga avisa.
 */
import { createHash } from 'node:crypto';
import { createReadStream, existsSync } from 'node:fs';
import { open, readdir } from 'node:fs/promises';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { from as copyFrom } from 'pg-copy-streams';
import { pool, prisma } from '../db/prisma.js';
import { CURRENCIES } from '../lib/domain.js';

const DIMENSIONS = ['branches', 'customers', 'products', 'daily_exchange_rates'] as const;
/** Colunas dos CSVs de transações (a tabela tem colunas extras para as operações simuladas e a linhagem). */
const TRANSACTION_COLUMNS = [
  'transaction_id', 'transaction_date', 'process_date', 'product_id', 'customer_id',
  'transaction_type', 'transaction_category', 'amount', 'currency', 'amount_usd', 'channel',
  'branch_id', 'merchant_name', 'merchant_category', 'transaction_country', 'transaction_city',
  'transaction_status', 'response_code', 'is_fraud', 'fraud_score', 'latitude', 'longitude',
];
const FRESHNESS_DAYS = 1;

const IN_CURRENCIES = `IN (${CURRENCIES.map((c) => `'${c}'`).join(', ')})`;
/** Regras de domínio além do tipo da coluna (SQL sobre os valores ainda em texto). */
const RULES: Record<string, Record<string, string>> = {
  transactions: {
    currency: `currency ${IN_CURRENCIES}`,
    transaction_status: `transaction_status IN ('Approved', 'Declined', 'Pending', 'Reversed')`,
  },
  products: { currency: `currency ${IN_CURRENCIES}` },
  daily_exchange_rates: {
    source_currency: `source_currency ${IN_CURRENCIES}`,
    target_currency: `target_currency ${IN_CURRENCIES}`,
  },
};
/** Normalizações feitas na carga. O dataset mistura "Mexico" e "México". */
const TRANSFORMS: Record<string, Record<string, string>> = {
  transactions: { transaction_country: `CASE WHEN transaction_country = 'Mexico' THEN 'México' ELSE transaction_country END` },
};

export interface LoadOptions {
  dataDir: string;
  /** Apaga tudo (inclusive operações simuladas e o manifesto) e recarrega do zero. */
  force?: boolean;
  concurrency?: number;
  log?: (message: string) => void;
}

export interface LoadResult {
  files_loaded: number;
  files_skipped: number;
  rows_loaded: number;
  rows_rejected: number;
  latest_partition: string | null;
  customers: number;
  products: number;
  transactions: number;
}

interface Column {
  name: string;
  type: string;
  not_null: boolean;
}

interface SourceFile {
  table: string;
  abs: string;
  /** Caminho relativo ao DATA_DIR: chave da linhagem. */
  rel: string;
  /** YYYY-MM-DD da partição diária (só transações). */
  partition: string | null;
}

async function listCsvFiles(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  return entries
    .filter((e) => e.isFile() && e.name.endsWith('.csv'))
    .map((e) => path.join(e.parentPath, e.name))
    .sort();
}

async function sha256(file: string): Promise<string> {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

async function readHeader(file: string): Promise<string> {
  const fh = await open(file);
  const { buffer, bytesRead } = await fh.read(Buffer.alloc(64 * 1024), 0, 64 * 1024, 0);
  await fh.close();
  return buffer.toString('utf8', 0, bytesRead).split(/\r?\n/)[0].replace(/^﻿/, '');
}

/** Colunas esperadas no CSV, com o tipo do Postgres de cada uma: é o contrato do arquivo. */
async function contract(table: string): Promise<Column[]> {
  const { rows } = await pool.query<Column>(
    `SELECT attname AS name, format_type(atttypid, atttypmod) AS type, attnotnull AS not_null
       FROM pg_attribute WHERE attrelid = $1::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum`,
    [table],
  );
  if (table !== 'transactions') return rows;
  return TRANSACTION_COLUMNS.map((name) => rows.find((c) => c.name === name)!);
}

/** Carrega um arquivo numa transação: valida, troca as linhas antigas dele e grava a linhagem. */
async function loadFile(f: SourceFile, columns: Column[], hash: string) {
  const names = columns.map((c) => c.name);
  const header = await readHeader(f.abs);
  if (header !== names.join(',')) {
    throw new Error(`${f.rel}: cabeçalho fora do contrato.\n  esperado: ${names.join(',')}\n  recebido: ${header}`);
  }

  // Uma expressão por motivo de rejeição: o tipo de cada coluna (+ regra de domínio) e a partição do arquivo.
  const q = (name: string) => `"${name}"`;
  const checks: Record<string, string> = {};
  for (const c of columns) {
    const typed = `pg_input_is_valid(${q(c.name)}, '${c.type}')`;
    checks[c.name] = c.not_null ? `${q(c.name)} IS NOT NULL AND ${typed}` : `(${q(c.name)} IS NULL OR ${typed})`;
  }
  for (const [name, rule] of Object.entries(RULES[f.table] ?? {})) checks[name] += ` AND ${rule}`;
  if (f.partition) checks.partition = `process_date = '${f.partition}'`;
  const ok = (expr: string) => `coalesce(${expr}, false)`;
  const valid = Object.values(checks).map(ok).join(' AND ');

  const isFact = f.table === 'transactions';
  const select = columns.map((c) => `(${TRANSFORMS[f.table]?.[c.name] ?? q(c.name)})::${c.type}`);
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query(`CREATE TEMP TABLE stage (${names.map((n) => `${q(n)} text`).join(', ')}) ON COMMIT DROP`);
    await pipeline(createReadStream(f.abs), client.query(copyFrom('COPY stage FROM STDIN WITH (FORMAT csv, HEADER true)')));

    const reasons = Object.entries(checks).map(([name, expr]) => `count(*) FILTER (WHERE NOT ${ok(expr)})::int AS ${q(name)}`);
    const { rows: [stats] } = await client.query<Record<string, number>>(
      `SELECT count(*)::int AS rows_read, count(*) FILTER (WHERE ${valid})::int AS rows_valid, ${reasons.join(', ')} FROM stage`,
    );

    await client.query(isFact ? 'DELETE FROM transactions WHERE source_file = $1' : `TRUNCATE ${f.table}`, isFact ? [f.rel] : []);
    const inserted = await client.query(
      `INSERT INTO ${f.table} (${names.map(q).join(', ')}${isFact ? ', source_file' : ''})
       SELECT ${select.join(', ')}${isFact ? ', $1::text' : ''} FROM stage WHERE ${valid}
       ON CONFLICT DO NOTHING`,
      isFact ? [f.rel] : [],
    );

    const { rows_read, rows_valid, ...byReason } = stats;
    const rowsLoaded = inserted.rowCount!;
    const rejects = Object.fromEntries(Object.entries(byReason).filter(([, n]) => n > 0));
    if (rows_valid > rowsLoaded) rejects.duplicate_key = rows_valid - rowsLoaded;
    await client.query(
      `INSERT INTO etl_files (file, target_table, partition_date, sha256, rows_read, rows_loaded, rows_rejected, rejects)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       ON CONFLICT (file) DO UPDATE SET target_table = EXCLUDED.target_table, partition_date = EXCLUDED.partition_date,
         sha256 = EXCLUDED.sha256, rows_read = EXCLUDED.rows_read, rows_loaded = EXCLUDED.rows_loaded,
         rows_rejected = EXCLUDED.rows_rejected, rejects = EXCLUDED.rejects, loaded_at = now()`,
      [f.rel, f.table, f.partition, hash, rows_read, rowsLoaded, rows_read - rowsLoaded, rejects],
    );
    await client.query('COMMIT');
    return { rowsLoaded, rowsRejected: rows_read - rowsLoaded, rejects };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

async function counts() {
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

  const sources: SourceFile[] = [
    ...DIMENSIONS.map((table) => path.join(dir, `${table}.csv`)),
    ...(await listCsvFiles(path.join(dir, 'transactions'))),
  ].map((abs) => {
    const rel = path.relative(dir, abs).split(path.sep).join('/');
    const table = rel.startsWith('transactions/') ? 'transactions' : path.basename(rel, '.csv');
    const day = /^transactions\/year=(\d{4})\/month=(\d{2})\/day=(\d{2})\/[^/]+$/.exec(rel);
    if (table === 'transactions' && !day) throw new Error(`${rel}: transações têm que estar em transactions/year=/month=/day=.`);
    return { table, abs, rel, partition: day && `${day[1]}-${day[2]}-${day[3]}` };
  });

  // Primeira carga, --force ou banco carregado antes da linhagem existir: começa do zero.
  if (force || (await prisma.etlFile.count()) === 0) {
    log(`Carga completa de ${dir}`);
    await prisma.$executeRawUnsafe(`TRUNCATE ${[...DIMENSIONS, 'transactions', 'scheduled_payments', 'etl_files'].join(', ')}`);
  } else {
    log(`Carga incremental de ${dir}`);
  }
  const previous = new Map((await prisma.etlFile.findMany({ select: { file: true, sha256: true } })).map((f) => [f.file, f.sha256]));
  const contracts = new Map<string, Column[]>();
  for (const table of [...DIMENSIONS, 'transactions']) contracts.set(table, await contract(table));

  const totals = { files_loaded: 0, files_skipped: 0, rows_loaded: 0, rows_rejected: 0 };
  const loadOne = async (f: SourceFile) => {
    const hash = await sha256(f.abs);
    if (previous.get(f.rel) === hash) {
      totals.files_skipped += 1;
      return;
    }
    const r = await loadFile(f, contracts.get(f.table)!, hash);
    totals.files_loaded += 1;
    totals.rows_loaded += r.rowsLoaded;
    totals.rows_rejected += r.rowsRejected;
    if (r.rowsRejected) log(`  ${f.rel}: ${r.rowsRejected} linha(s) rejeitada(s) ${JSON.stringify(r.rejects)}`);
  };

  // Dimensões em sequência (cada uma troca a tabela inteira); partições de transações em paralelo.
  for (const f of sources.filter((s) => s.table !== 'transactions')) await loadOne(f);
  const queue = sources.filter((s) => s.table === 'transactions');
  const total = queue.length;
  let done = 0;
  await Promise.all(
    Array.from({ length: concurrency }, async () => {
      for (let f = queue.shift(); f; f = queue.shift()) {
        await loadOne(f);
        done += 1;
        if (done % 100 === 0 || done === total) log(`  transactions: ${done}/${total} arquivos`);
      }
    }),
  );
  if (totals.files_loaded) await prisma.$executeRawUnsafe('ANALYZE');

  const [{ latest, age_days }] = await prisma.$queryRaw<{ latest: string | null; age_days: number | null }[]>`
    SELECT max(partition_date)::text AS latest, current_date - max(partition_date) AS age_days FROM etl_files`;
  if (age_days! > FRESHNESS_DAYS) {
    log(`AVISO: a última partição carregada é ${latest} (${age_days} dias atrás); o esperado é a partição D chegar até D+${FRESHNESS_DAYS}.`);
  }

  const result = { ...totals, latest_partition: latest, ...(await counts()) };
  log(`Carga concluída: ${JSON.stringify(result)}`);
  return result;
}
