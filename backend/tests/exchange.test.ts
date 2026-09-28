import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { resetData, testApp } from './helpers.js';

let app: FastifyInstance;
beforeAll(async () => {
  await resetData();
  app = await testApp();
});
afterAll(() => app.close());

describe('câmbio (feature 4)', () => {
  it('cotação mais recente por padrão', async () => {
    const body = (await app.inject('/api/exchange-rates?from=USD&to=COP')).json();
    expect(body).toMatchObject({ source_currency: 'USD', target_currency: 'COP', rate_date: '2026-06-17', exchange_rate: 4000, source: 'Central Bank' });
    expect(body.buy_rate).toBe(3960);
  });

  it('cotação da data pedida (ou a última antes dela)', async () => {
    const body = (await app.inject('/api/exchange-rates?from=USD&to=MXN&date=2026-06-16')).json();
    expect(body).toMatchObject({ rate_date: '2026-06-16', exchange_rate: 18.18 });
    const later = (await app.inject('/api/exchange-rates?from=USD&to=MXN&date=2026-09-01')).json();
    expect(later.rate_date).toBe('2026-06-17');
  });

  it('mesma moeda tem taxa 1', async () => {
    const body = (await app.inject('/api/exchange-rates?from=ARS&to=ARS')).json();
    expect(body).toMatchObject({ exchange_rate: 1, rate_date: null, source: null });
  });

  it('404 quando não há cotação até a data', async () => {
    const res = await app.inject('/api/exchange-rates?from=USD&to=COP&date=2020-01-01');
    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({ error: 'rate_not_found', message: 'Não há cotação de USD para COP até 2020-01-01.' });
  });

  it('400 para moeda não suportada', async () => {
    expect((await app.inject('/api/exchange-rates?from=USD&to=EUR')).statusCode).toBe(400);
  });

  it('converte valores', async () => {
    const body = (await app.inject('/api/exchange-rates/convert?from=MXN&to=ARS&amount=180')).json();
    expect(body).toMatchObject({ amount: 180, converted_amount: 10000 });
    expect(body.rate.exchange_rate).toBeCloseTo(55.5555555556, 8);
  });

  it('histórico diário e pares disponíveis', async () => {
    const history = (await app.inject('/api/exchange-rates/history?from=COP&to=USD&start=2026-06-01&end=2026-06-30')).json();
    expect(history.map((r: { date: string }) => r.date)).toEqual(['2026-06-16', '2026-06-17']);

    const pairs = (await app.inject('/api/exchange-rates/pairs')).json();
    expect(pairs).toHaveLength(12);
    expect(pairs[0]).toEqual({ source_currency: 'ARS', target_currency: 'COP', first_date: '2026-06-16', last_date: '2026-06-17' });
  });
});
