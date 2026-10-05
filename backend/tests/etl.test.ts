import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { prisma } from '../src/db/prisma.js';
import { loadData } from '../src/etl/load.js';
import { FIXTURES } from './helpers.js';

const INCREMENTAL = path.join(FIXTURES, '..', 'incremental');
const DAY19 = 'transactions/year=2026/month=06/day=19/transactions_20260619.csv';

/** Cópia das fixtures num diretório temporário, com `extra` (caminho relativo → conteúdo) por cima. */
async function dataDir(extra: Record<string, string> = {}, overlay?: string) {
  const dir = await mkdtemp(path.join(tmpdir(), 'etl-'));
  await cp(FIXTURES, dir, { recursive: true });
  if (overlay) await cp(overlay, dir, { recursive: true });
  for (const [file, content] of Object.entries(extra)) {
    await mkdir(path.dirname(path.join(dir, file)), { recursive: true });
    await writeFile(path.join(dir, file), content);
  }
  return dir;
}

const lineage = (file: string) => prisma.etlFile.findUniqueOrThrow({ where: { file } });

describe('ETL: carga completa', () => {
  it('carrega os CSVs, normaliza "Mexico" para "México" e grava a linhagem por arquivo', async () => {
    const log = vi.fn();
    const result = await loadData({ dataDir: FIXTURES, force: true, concurrency: 2, log });
    expect(result).toEqual({
      files_loaded: 7,
      files_skipped: 0,
      rows_loaded: 4 + 2 + 18 + 24 + 18,
      rows_rejected: 0,
      latest_partition: '2026-06-17',
      customers: 4,
      products: 18,
      transactions: 18,
    });
    expect(log).toHaveBeenCalledWith('  transactions: 3/3 arquivos');

    const t = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: 'TRX-T01' } });
    expect(t).toMatchObject({ transaction_country: 'México', origin: 'historical', source_file: 'transactions/year=2026/month=06/day=16/transactions_20260616.csv' });
    const branch = await prisma.branch.findUniqueOrThrow({ where: { branch_id: 'SUC-T0000001' } });
    expect(branch.opening_time).toBe('09:00:00');

    const day16 = await lineage('transactions/year=2026/month=06/day=16/transactions_20260616.csv');
    expect(day16).toMatchObject({ target_table: 'transactions', rows_read: 9, rows_loaded: 9, rows_rejected: 0, rejects: {} });
    expect(day16.partition_date?.toISOString().slice(0, 10)).toBe('2026-06-16');
    expect(day16.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(await lineage('customers.csv')).toMatchObject({ target_table: 'customers', partition_date: null, rows_loaded: 4 });
  });

  it('avisa quando a última partição está atrasada (política: partição D até D+1)', async () => {
    const log = vi.fn();
    await loadData({ dataDir: FIXTURES, log });
    expect(log).toHaveBeenCalledWith(expect.stringMatching(/^AVISO: a última partição carregada é 2026-06-17 \(\d+ dias atrás\)/));
  });

  it('rodar de novo sem mudanças não recarrega nada', async () => {
    const result = await loadData({ dataDir: FIXTURES, log: () => {} });
    expect(result).toMatchObject({ files_loaded: 0, files_skipped: 7, rows_loaded: 0, transactions: 18 });
  });

  it('banco sem manifesto (carregado antes da linhagem) faz carga completa', async () => {
    await prisma.etlFile.deleteMany();
    const log = vi.fn();
    const result = await loadData({ dataDir: FIXTURES, log });
    expect(log).toHaveBeenCalledWith(expect.stringMatching(/^Carga completa de /));
    expect(result).toMatchObject({ files_loaded: 7, transactions: 18 });
  });

  it('usa console.log e concorrência padrão quando não informados', async () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    await loadData({ dataDir: FIXTURES, force: true });
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe('ETL: carga incremental (fixture tests/fixtures/incremental)', () => {
  it('recarrega só a partição alterada e a nova, rejeitando linhas fora do contrato', async () => {
    await loadData({ dataDir: FIXTURES, force: true, log: () => {} });
    const simulated = await prisma.transaction.create({
      data: { transaction_id: 'TRX-SIMULATED', transaction_date: new Date(), amount: 1, currency: 'USD', customer_id: 'CLI-ANA000000001', origin: 'simulated' },
    });

    const log = vi.fn();
    const result = await loadData({ dataDir: await dataDir({}, INCREMENTAL), log });
    expect(log).toHaveBeenCalledWith(expect.stringMatching(/^Carga incremental de /));
    expect(result).toMatchObject({
      files_loaded: 2,
      files_skipped: 6,
      rows_loaded: 5 + 2,
      rows_rejected: 4,
      latest_partition: '2026-06-18',
      transactions: 18 - 1 + 2 + 1,
    });

    // Partição reenviada: a linha removida some e a corrigida é atualizada.
    expect(await prisma.transaction.findUnique({ where: { transaction_id: 'TRX-T16' } })).toBeNull();
    expect((await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: 'TRX-T06' } })).transaction_status).toBe('Approved');

    // Partição nova: linhas boas entram (normalizadas), as ruins são contadas por motivo.
    expect((await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: 'TRX-T19' } })).transaction_country).toBe('México');
    expect(await lineage('transactions/year=2026/month=06/day=18/transactions_20260618.csv')).toMatchObject({
      rows_read: 6,
      rows_loaded: 2,
      rows_rejected: 4,
      rejects: { currency: 1, amount: 1, partition: 1, duplicate_key: 1 },
    });
    expect(log).toHaveBeenCalledWith(expect.stringContaining('day=18/transactions_20260618.csv: 4 linha(s) rejeitada(s)'));
    // A duplicata não sobrescreve a linha original nem a sua linhagem.
    expect((await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: 'TRX-T01' } })).source_file).toContain('day=16');

    // Operações simuladas não são tocadas pela carga incremental.
    expect(await prisma.transaction.findUnique({ where: { transaction_id: simulated.transaction_id } })).not.toBeNull();
  });

  it('é idempotente: a mesma entrega de novo não muda nada', async () => {
    const result = await loadData({ dataDir: await dataDir({}, INCREMENTAL), log: () => {} });
    expect(result).toMatchObject({ files_loaded: 0, files_skipped: 8, transactions: 20 });
  });

  it('partição de hoje em dia: sem aviso de atraso', async () => {
    const today = new Date().toISOString().slice(0, 10);
    const [y, m, d] = today.split('-');
    const header = (await readFile(path.join(FIXTURES, 'transactions/year=2026/month=06/day=17/transactions_20260617.csv'), 'utf8')).split('\n')[0];
    const log = vi.fn();
    const result = await loadData({
      dataDir: await dataDir({ [`transactions/year=${y}/month=${m}/day=${d}/transactions_${y}${m}${d}.csv`]: `${header}\nTRX-TODAY,${today} 08:00:00,${today},,CLI-ANA000000001,Deposit,,1.00,USD,,,,,,México,,Approved,00,False,,,\n` }, INCREMENTAL),
      log,
    });
    expect(result).toMatchObject({ files_loaded: 1, latest_partition: today });
    expect(log).not.toHaveBeenCalledWith(expect.stringMatching(/^AVISO/));
  });
});

describe('ETL: arquivos fora do contrato', () => {
  const header = 'transaction_id,transaction_date,process_date,product_id,customer_id,transaction_type,transaction_category,amount,currency,amount_usd,channel,branch_id,merchant_name,merchant_category,transaction_country,transaction_city,transaction_status,response_code,is_fraud,fraud_score,latitude,longitude';
  const row = 'TRX-T99,2026-06-19 10:00:00,2026-06-19,,CLI-ANA000000001,Deposit,,1.00,USD,,,,,,México,,Approved,00,False,,,';

  it('cabeçalho diferente do esperado para a carga', async () => {
    const dir = await dataDir({ [DAY19]: `${header.replace(',longitude', '')}\n` });
    await expect(loadData({ dataDir: dir, log: () => {} })).rejects.toThrow(`${DAY19}: cabeçalho fora do contrato`);
  });

  it('CSV malformado aborta o arquivo inteiro, sem carga parcial nem linhagem', async () => {
    const dir = await dataDir({ [DAY19]: `${header}\n${row}\n${row.replace('TRX-T99', 'TRX-T98')},coluna-a-mais\n` });
    await expect(loadData({ dataDir: dir, log: () => {} })).rejects.toThrow(/extra data after last expected column/);
    expect(await prisma.transaction.findUnique({ where: { transaction_id: 'TRX-T99' } })).toBeNull();
    expect(await prisma.etlFile.findUnique({ where: { file: DAY19 } })).toBeNull();
  });

  it('transação fora de uma partição diária é recusada', async () => {
    const dir = await dataDir({ 'transactions/solto.csv': `${header}\n` });
    await expect(loadData({ dataDir: dir, log: () => {} })).rejects.toThrow('transactions/solto.csv: transações têm que estar em');
  });

  it('falha se o diretório não tiver os CSVs', async () => {
    await expect(loadData({ dataDir: '/nao/existe' })).rejects.toThrow('CSVs não encontrados');
  });
});
