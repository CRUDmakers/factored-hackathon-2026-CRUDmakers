import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ANA, DIEGO, UNKNOWN, ownerApp, resetData } from './helpers.js';

let app: FastifyInstance;
beforeAll(async () => {
  await resetData();
  app = await ownerApp();
});
afterAll(() => app.close());

describe('GET /api/customers/:id', () => {
  it('retorna o cliente', async () => {
    const res = await app.inject(`/api/customers/${ANA}`);
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ customer_id: ANA, first_name: 'Ana', country: 'México' });
  });

  it('404 para cliente inexistente', async () => {
    const res = await app.inject(`/api/customers/${UNKNOWN}`);
    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({ error: 'not_found' });
  });

  it('400 para ID fora do formato', async () => {
    const res = await app.inject('/api/customers/abc');
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe('validation_error');
  });
});

describe('GET /api/customers/:id/balances (feature 1)', () => {
  it('consolida contas, cartões, empréstimos e investimentos', async () => {
    const body = (await app.inject(`/api/customers/${ANA}/balances`)).json();

    // Produtos fechados ficam de fora.
    expect(body.accounts.map((a: { product_id: string }) => a.product_id)).not.toContain('PRD-ANACLOSED008');
    expect(body.accounts).toContainEqual(
      expect.objectContaining({ product_id: 'PRD-ANACHK000001', balance: 1000, product_number: '4000000001' }),
    );

    const card = body.credit_cards.find((c: { product_id: string }) => c.product_id === 'PRD-ANACC0000003');
    expect(card).toMatchObject({
      invoice_amount: 200,
      credit_limit: 1000,
      available_credit: 800,
      utilization_pct: 20,
      expiration_date: '2099-01-01',
    });
    const noLimit = body.credit_cards.find((c: { product_id: string }) => c.product_id === 'PRD-ANACCZERO010');
    expect(noLimit).toMatchObject({ invoice_amount: 0, credit_limit: 0, utilization_pct: null, product_number: null });

    expect(body.loans).toHaveLength(2);
    expect(body.investments).toEqual([expect.objectContaining({ product_id: 'PRD-ANAINV000007', balance: 3000 })]);

    const usd = body.totals_by_currency.find((t: { currency: string }) => t.currency === 'USD');
    // contas 1000 + 300 (débito bloqueado) + 500 (débito vencido); dívidas 200 + 0 + 0 + 5000 + 0; investimento 3000
    expect(usd).toMatchObject({ available_funds: 1800, debt: 5200, investments: 3000, net: -400, usd_rate: 1 });
    const cop = body.totals_by_currency.find((t: { currency: string }) => t.currency === 'COP');
    expect(cop).toMatchObject({ available_funds: 5000000, usd_rate_date: '2026-06-17' });
    expect(body.net_worth_usd).toBe(-400 + 5000000 * 0.00025);
  });

  it('cliente sem produtos', async () => {
    const body = (await app.inject(`/api/customers/${DIEGO}/balances`)).json();
    expect(body).toMatchObject({ accounts: [], credit_cards: [], totals_by_currency: [], net_worth_usd: 0 });
  });
});

describe('produtos (feature 10)', () => {
  it('lista com filtros de tipo e status', async () => {
    const all = (await app.inject(`/api/customers/${ANA}/products`)).json();
    expect(all).toHaveLength(12);

    const cards = (await app.inject(`/api/customers/${ANA}/products?type=Tarjeta%20Cr%C3%A9dito&status=Active`)).json();
    expect(cards.map((p: { product_id: string }) => p.product_id)).toEqual([
      'PRD-ANACC0000003',
      'PRD-ANACCEXP0004',
      'PRD-ANACCZERO010',
    ]);
  });

  it('mostra vencimento, juros e se está vencido', async () => {
    const valid = (await app.inject(`/api/customers/${ANA}/products/PRD-ANACC0000003`)).json();
    expect(valid).toMatchObject({ expiration_date: '2099-01-01', is_expired: false, interest_rate: 22.5, available_credit: 800 });

    const expired = (await app.inject(`/api/customers/${ANA}/products/PRD-ANACCEXP0004`)).json();
    expect(expired).toMatchObject({ expiration_date: '2024-01-01', is_expired: true });

    const account = (await app.inject(`/api/customers/${ANA}/products/PRD-ANACHK000001`)).json();
    expect(account).toMatchObject({ expiration_date: null, is_expired: false, available_credit: null });
  });

  it('404 para produto de outro cliente ou cliente inexistente', async () => {
    expect((await app.inject(`/api/customers/${ANA}/products/PRD-BRUCHK000001`)).statusCode).toBe(404);
    expect((await app.inject(`/api/customers/${UNKNOWN}/products`)).statusCode).toBe(404);
  });
});
