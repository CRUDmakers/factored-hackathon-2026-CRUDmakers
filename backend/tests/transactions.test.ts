import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { resolvePeriod } from '../src/services/transactions.js';
import { ANA, BRUNO, DIEGO, UNKNOWN, ownerApp, resetData } from './helpers.js';

let app: FastifyInstance;
beforeAll(async () => {
  await resetData();
  app = await ownerApp();
});
afterAll(() => app.close());

const ids = (items: { transaction_id: string }[]) => items.map((t) => t.transaction_id);

describe('GET /transactions (feature 6)', () => {
  it('lista as mais recentes primeiro, com paginação padrão', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/transactions`)).json();
    expect(body).toMatchObject({ total: 17, limit: 50, offset: 0 });
    expect(body.items[0]).toMatchObject({ transaction_id: 'TRX-T15', direction: 'out', category: 'Transfers', product_type: null });
  });

  it('calcula valor em USD: amount_usd, USD direto ou cotação do dia', async () => {
    const items = (await app.inject(`/api/customers/${ANA}/transactions?limit=100`)).json().items;
    const byId = Object.fromEntries(items.map((t: { transaction_id: string }) => [t.transaction_id, t]));
    expect(byId['TRX-T12'].amount_usd).toBe(2.5);
    expect(byId['TRX-T02'].amount_usd).toBe(100);
    expect(byId['TRX-T04'].amount_usd).toBe(101); // 400000 COP * (0.00025 * 1.01) em 2026-06-16
    expect(byId['TRX-T03'].direction).toBe('in');
    expect(byId['TRX-T08'].direction).toBe('adjustment');
    expect(byId['TRX-T05'].status_reason).toBe('Saldo ou limite insuficiente.');
  });

  it('aplica todos os filtros', async () => {
    const q = 'from=2026-06-16&to=2026-06-17&type=Purchase&status=Approved&category=Food&channel=POS' +
      '&product_id=PRD-ANACC0000003&origin=historical&limit=10&offset=0';
    const body = (await app.inject(`/api/customers/${ANA}/transactions?${q}`)).json();
    expect(ids(body.items)).toEqual(['TRX-T01']);
    expect(body.total).toBe(1);
  });

  it('pagina com limit/offset', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/transactions?limit=2&offset=1`)).json();
    expect(ids(body.items)).toEqual(['TRX-T14', 'TRX-T13']);
  });

  it('404 para cliente inexistente e 400 para filtro inválido', async () => {
    expect((await app.inject(`/api/customers/${UNKNOWN}/transactions`)).statusCode).toBe(404);
    expect((await app.inject(`/api/customers/${ANA}/transactions?limit=0`)).statusCode).toBe(400);
  });
});

describe('detalhe e local da transação (features 5 e 8)', () => {
  it('saque em ATM mostra a agência e as coordenadas válidas', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/transactions/TRX-T02`)).json();
    expect(body).toMatchObject({ transaction_type: 'Withdrawal', product_type: 'Cuenta Corriente', process_date: '2026-06-17' });
    expect(body.status).toMatchObject({ status: 'Approved', completed: true });
    expect(body.location.summary).toBe('Caixa eletrônico (ATM): agência Banco LATAM CDMX Centro — Av. Reforma 100, Centro, Ciudad de México');
    expect(body.location.branch).toMatchObject({ branch_id: 'SUC-T0000001', atm_count: 4, coordinates: { latitude: 19.4326, longitude: -99.1332 } });
    expect(body.location.coordinates).toBeNull();
  });

  it('agência com coordenadas inválidas (0,0) volta sem coordenadas', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/transactions/TRX-T08`)).json();
    expect(body.location.branch.coordinates).toBeNull();
  });

  it('compra em maquininha mostra estabelecimento e coordenadas da transação', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/transactions/TRX-T01`)).json();
    expect(body.location).toMatchObject({
      summary: 'Maquininha (POS) em Tacos El Güero: Ciudad de México',
      coordinates: { latitude: 19.4, longitude: -99.1 },
      branch: null,
      country: 'México',
    });
  });

  it('transação sem produto e sem canal', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/transactions/TRX-T15`)).json();
    expect(body).toMatchObject({ product_id: null, product_type: null });
    expect(body.location.summary).toBe('Canal digital (não informado)');
  });

  it('status de pagamento negado explica o motivo (feature 5)', async () => {
    const res = await app.inject(`/api/customers/${ANA}/transactions/TRX-T05/status`);
    expect(res.json()).toMatchObject({
      transaction_id: 'TRX-T05',
      status: 'Declined',
      completed: false,
      reason_code: 'insufficient_funds',
      amount: 30,
    });
  });

  it('404 para transação de outro cliente', async () => {
    expect((await app.inject(`/api/customers/${BRUNO}/transactions/TRX-T01`)).statusCode).toBe(404);
    expect((await app.inject(`/api/customers/${BRUNO}/transactions/TRX-T01/status`)).statusCode).toBe(404);
  });
});

describe('relatório de transações (feature 6)', () => {
  it('período padrão: 30 dias até a última transação', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/reports/transactions`)).json();
    expect(body.period).toEqual({ from: '2026-05-19', to: '2026-06-17' });
    expect(body.summary).toMatchObject({ transactions: 17, approved: 13, inflow_usd: 2000 });
    // saídas aprovadas: 50 + 100 + 2.5 + 20 + 30 + 15 + 101 + 80 (ajustes não entram)
    expect(body.summary.outflow_usd).toBe(398.5);
    expect(body.summary.net_usd).toBe(1601.5);
    expect(body.by_status).toEqual([
      { transaction_status: 'Approved', count: 13 },
      { transaction_status: 'Pending', count: 2 },
      { transaction_status: 'Declined', count: 1 },
      { transaction_status: 'Reversed', count: 1 },
    ]);
    expect(body.spending_by_category[0]).toMatchObject({ category: 'Withdrawals', count: 3, total_usd: 150 });
    expect(body.by_month.map((m: { month: string }) => m.month)).toEqual(['2026-05', '2026-06']);
    expect(body.top_merchants[0]).toMatchObject({ merchant_name: 'Farmacia', total_usd: 80 });
    expect(body.not_completed.map((t: { transaction_id: string }) => t.transaction_id)).toEqual(['TRX-T16', 'TRX-T06', 'TRX-T05', 'TRX-T17']);
    expect(body.not_completed[0]).toMatchObject({ status: 'Pending', reason_code: 'do_not_honor' });
  });

  it('respeita o período informado', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/reports/transactions?from=2026-06-17&to=2026-06-17`)).json();
    expect(body.period).toEqual({ from: '2026-06-17', to: '2026-06-17' });
    expect(body.summary.transactions).toBe(6);
  });

  it('404 para cliente inexistente', async () => {
    expect((await app.inject(`/api/customers/${UNKNOWN}/reports/transactions`)).statusCode).toBe(404);
  });
});

describe('resolvePeriod', () => {
  it('usa só o `to` informado e calcula o início', async () => {
    expect(await resolvePeriod(ANA, undefined, '2026-06-30', 10)).toEqual({ from: '2026-06-21', to: '2026-06-30' });
  });

  it('cliente sem transações usa a data de hoje', async () => {
    const today = new Date().toISOString().slice(0, 10);
    expect((await resolvePeriod(DIEGO)).to).toBe(today);
  });
});

describe('gastos por categoria (feature 7)', () => {
  it('agrupa gastos aprovados por categoria e mês-calendário, em USD, com variação mês a mês', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/reports/spending`)).json();
    expect(body.period).toEqual({ from: '2026-04-01', to: '2026-06-17' });
    expect(body.total_spent_usd).toBe(398.5);
    expect(body.monthly_average_usd).toBe(132.83);
    expect(body.by_category[0]).toMatchObject({ category: 'Withdrawals', count: 3, total_usd: 150, share_pct: 37.64 });
    expect(body.by_month).toEqual([
      { month: '2026-04', total_usd: 0, change_pct: null, categories: {} },
      { month: '2026-05', total_usd: 80, change_pct: null, categories: { Health: 80 } },
      expect.objectContaining({ month: '2026-06', total_usd: 318.5, change_pct: 298.13 }),
    ]);
  });

  it('`months` define quantos meses inteiros entram no período', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/reports/spending?months=1`)).json();
    expect(body.period).toEqual({ from: '2026-06-01', to: '2026-06-17' });
    expect(body.by_month.map((m: { month: string }) => m.month)).toEqual(['2026-06']);
  });

  it('by_product reparte o total por cartão/conta; product_id filtra o resto', async () => {
    const all = (await app.inject(`/api/customers/${ANA}/reports/spending`)).json();
    const sum = all.by_product.reduce((n: number, p: { total_usd: number }) => n + p.total_usd, 0);
    expect(sum).toBeCloseTo(398.5, 2);
    expect(all.by_product[0].by_month.map((m: { month: string }) => m.month)).toEqual(['2026-04', '2026-05', '2026-06']);

    const card = all.by_product.find((p: { product_id: string }) => p.product_id === 'PRD-ANACC0000003');
    const one = (await app.inject(`/api/customers/${ANA}/reports/spending?product_id=PRD-ANACC0000003`)).json();
    expect(one.product_id).toBe('PRD-ANACC0000003');
    expect(one.total_spent_usd).toBe(card.total_usd);
    expect(one.by_category.map((c: { category: string }) => c.category)).toContain('Food');
    expect(one.by_product).toEqual(all.by_product);
  });

  it('período sem gastos', async () => {
    const body = (await app.inject(`/api/customers/${DIEGO}/reports/spending?from=2026-01-01&to=2026-01-31`)).json();
    expect(body).toMatchObject({
      total_spent_usd: 0,
      monthly_average_usd: 0,
      by_category: [],
      by_month: [{ month: '2026-01', total_usd: 0, change_pct: null, categories: {} }],
      by_product: [],
    });
  });

  it('404 para cliente inexistente e 400 para months inválido', async () => {
    expect((await app.inject(`/api/customers/${UNKNOWN}/reports/spending`)).statusCode).toBe(404);
    expect((await app.inject(`/api/customers/${ANA}/reports/spending?months=0`)).statusCode).toBe(400);
  });
});

describe('ajustes (feature 9)', () => {
  it('por padrão lista só ajustes de empréstimos, com explicação', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/adjustments`)).json();
    expect(ids(body)).toEqual(['TRX-T11', 'TRX-T08']);
    const personal = body.find((a: { transaction_id: string }) => a.transaction_id === 'TRX-T08');
    expect(personal.product).toMatchObject({ product_type: 'Préstamo Personal', days_past_due: 10, expiration_date: '2030-01-01' });
    expect(personal.explanation).toContain('10 dia(s) de atraso');
    expect(personal.completed).toBe(true);
  });

  it('loans_only=false inclui investimento e seguro; filtra por produto e limita', async () => {
    const all = (await app.inject(`/api/customers/${ANA}/adjustments?loans_only=false&limit=10`)).json();
    expect(ids(all)).toEqual(['TRX-T11', 'TRX-T10', 'TRX-T09', 'TRX-T08']);

    const one = (await app.inject(`/api/customers/${ANA}/adjustments?loans_only=false&product_id=PRD-ANAINV000007`)).json();
    expect(ids(one)).toEqual(['TRX-T09']);
  });

  it('404 para cliente inexistente', async () => {
    expect((await app.inject(`/api/customers/${UNKNOWN}/adjustments`)).statusCode).toBe(404);
  });
});
