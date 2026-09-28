import { describe, expect, it, vi } from 'vitest';
import { prisma } from '../src/db/prisma.js';
import { loadData } from '../src/etl/load.js';
import { FIXTURES } from './helpers.js';

describe('ETL', () => {
  it('carrega os CSVs e normaliza "Mexico" para "México"', async () => {
    const log = vi.fn();
    const result = await loadData({ dataDir: FIXTURES, force: true, concurrency: 2, log });
    expect(result).toEqual({ skipped: false, customers: 4, products: 18, transactions: 18 });
    expect(log).toHaveBeenCalledWith('  transactions: 3/3 arquivos');

    const t = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: 'TRX-T01' } });
    expect(t.transaction_country).toBe('México');
    expect(t.origin).toBe('historical');
    const branch = await prisma.branch.findUniqueOrThrow({ where: { branch_id: 'SUC-T0000001' } });
    expect(branch.opening_time).toBe('09:00:00');
  });

  it('não recarrega se já houver dados, a menos que force=true', async () => {
    const log = vi.fn();
    const result = await loadData({ dataDir: FIXTURES, log });
    expect(result.skipped).toBe(true);
    expect(log).toHaveBeenCalledWith('Dados já carregados. Use --force para recarregar.');
  });

  it('usa console.log e concorrência padrão quando não informados', async () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    await loadData({ dataDir: FIXTURES, force: true });
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it('falha se o diretório não tiver os CSVs', async () => {
    await expect(loadData({ dataDir: '/nao/existe' })).rejects.toThrow('CSVs não encontrados');
  });
});
