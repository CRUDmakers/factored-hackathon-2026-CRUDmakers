import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { prisma } from '../src/db/prisma.js';
import { ANA, SERVICE, UNKNOWN, balanceOf, ownerApp, resetData } from './helpers.js';

let app: FastifyInstance;
beforeAll(async () => {
  app = await ownerApp();
});
beforeEach(resetData);
afterAll(() => app.close());

const CHK = 'PRD-ANACHK000001';
const base = `/api/customers/${ANA}/scheduled-payments`;

const create = (payload: object) => app.inject({ method: 'POST', url: base, payload });
const run = async () => (await app.inject({ method: 'POST', url: '/api/scheduled-payments/run', headers: SERVICE })).json().executed;
const get = async (id: string) => (await app.inject(`${base}/${id}`)).json();

const transfer = (extra: object = {}) => ({
  source_product_id: CHK,
  method: 'transfer',
  amount: 100,
  destination: { to_product_id: 'PRD-BRUCHK000001' },
  frequency: 'once',
  ...extra,
});

describe('criação e consulta (feature 3)', () => {
  it('cria um agendamento único que vence imediatamente', async () => {
    const res = await create(transfer());
    expect(res.statusCode).toBe(201);
    expect(res.json()).toMatchObject({
      scheduled_payment_id: expect.stringMatching(/^SCH-/),
      status: 'active',
      frequency: 'once',
      max_executions: 1,
      currency: 'USD',
      amount: 100,
      end_date: null,
      executions: [],
    });
  });

  it('cria recorrente com início futuro, fim, limite e descrição', async () => {
    const body = (
      await create(
        transfer({
          frequency: 'monthly',
          start_at: '2099-01-31T12:00:00Z',
          end_date: '2099-12-31',
          max_executions: 6,
          currency: 'MXN',
          description: 'aluguel',
        }),
      )
    ).json();
    expect(body).toMatchObject({ next_run_at: '2099-01-31T12:00:00.000Z', end_date: '2099-12-31', max_executions: 6, currency: 'MXN', description: 'aluguel' });
    expect(await run()).toEqual([]); // ainda não venceu
  });

  it.each([
    ['início no passado', { start_at: '2020-01-01T00:00:00Z' }, 'invalid_start_at'],
    ['fim antes do início', { start_at: '2099-01-10T00:00:00Z', end_date: '2099-01-01' }, 'invalid_end_date'],
    ['origem inválida para o método', { method: 'pix', source_product_id: 'PRD-ANACC0000003', destination: { pix_key: 'x' } }, 'invalid_source_product'],
  ])('422 para %s', async (_, extra, error) => {
    const res = await create(transfer(extra));
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe(error);
  });

  it('404 para cliente inexistente', async () => {
    const res = await app.inject({ method: 'POST', url: `/api/customers/${UNKNOWN}/scheduled-payments`, payload: transfer() });
    expect(res.statusCode).toBe(404);
    expect((await app.inject(`/api/customers/${UNKNOWN}/scheduled-payments`)).statusCode).toBe(404);
  });

  it('lista com e sem filtro de status e 404 para agendamento inexistente', async () => {
    await create(transfer());
    const paused = (await create(transfer({ frequency: 'weekly' }))).json();
    await app.inject({ method: 'PATCH', url: `${base}/${paused.scheduled_payment_id}`, payload: { status: 'paused' } });

    expect((await app.inject(base)).json()).toHaveLength(2);
    const onlyPaused = (await app.inject(`${base}?status=paused`)).json();
    expect(onlyPaused.map((s: { scheduled_payment_id: string }) => s.scheduled_payment_id)).toEqual([paused.scheduled_payment_id]);
    expect((await app.inject(`${base}/SCH-NAOEXISTE`)).statusCode).toBe(404);
  });
});

describe('alteração e cancelamento', () => {
  it('pausa, retoma e altera campos', async () => {
    const { scheduled_payment_id: id } = (await create(transfer({ frequency: 'weekly' }))).json();
    const patch = (payload: object) => app.inject({ method: 'PATCH', url: `${base}/${id}`, payload });

    expect((await patch({ status: 'paused' })).json().status).toBe('paused');
    expect(await run()).toEqual([]); // pausado não executa

    const updated = (
      await patch({ status: 'active', amount: 42.5, next_run_at: '2099-05-01T10:00:00Z', end_date: '2099-12-31', description: 'novo' })
    ).json();
    expect(updated).toMatchObject({ status: 'active', amount: 42.5, next_run_at: '2099-05-01T10:00:00.000Z', end_date: '2099-12-31', description: 'novo' });

    expect((await patch({})).json()).toMatchObject({ amount: 42.5, description: 'novo' });
  });

  it('cancela e impede novas alterações', async () => {
    const { scheduled_payment_id: id } = (await create(transfer())).json();
    const cancelled = await app.inject({ method: 'DELETE', url: `${base}/${id}` });
    expect(cancelled.json()).toMatchObject({ status: 'cancelled', next_run_at: null });

    const again = await app.inject({ method: 'DELETE', url: `${base}/${id}` });
    expect(again.statusCode).toBe(409);
    expect(again.json()).toMatchObject({ error: 'schedule_closed' });
    expect((await app.inject({ method: 'PATCH', url: `${base}/${id}`, payload: { amount: 1 } })).statusCode).toBe(409);
    expect(await run()).toEqual([]);
  });
});

describe('execução', () => {
  it('agendamento único aprovado é concluído e movimenta o saldo', async () => {
    const { scheduled_payment_id: id } = (await create(transfer())).json();
    const [result] = await run();
    expect(result).toMatchObject({ scheduled_payment_id: id, result: 'Approved', status: 'completed' });
    expect(await balanceOf(CHK)).toBe(900);

    const schedule = await get(id);
    expect(schedule).toMatchObject({ status: 'completed', executions_count: 1, next_run_at: null, last_transaction_id: result.transaction_id });
    expect(schedule.executions).toEqual([expect.objectContaining({ transaction_id: result.transaction_id, transaction_status: 'Approved' })]);

    const tx = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: result.transaction_id } });
    expect(tx).toMatchObject({ scheduled_payment_id: id, description: `Pagamento agendado ${id}` });
  });

  it('agendamento único negado fica como failed', async () => {
    (await create(transfer({ amount: 5000, description: 'caro' }))).json();
    const [result] = await run();
    expect(result).toMatchObject({ status: 'failed', result: expect.stringMatching(/^Declined \(51\): Saldo disponível/) });
  });

  it('recorrente negado continua ativo e agenda a próxima execução', async () => {
    const { scheduled_payment_id: id } = (
      await create({ source_product_id: CHK, method: 'pix', amount: 5, destination: { pix_key: 'ninguem@test.com' }, frequency: 'weekly' })
    ).json();
    const [result] = await run();
    expect(result).toMatchObject({ status: 'active', result: expect.stringMatching(/^Declined \(14\)/) });
    const schedule = await get(id);
    expect(new Date(schedule.next_run_at).getTime()).toBeGreaterThan(Date.now() + 6 * 86_400_000);
  });

  it('mensal termina ao atingir max_executions', async () => {
    const { scheduled_payment_id: id } = (
      await create({
        source_product_id: CHK,
        method: 'bill_payment',
        amount: 10,
        destination: { barcode: '1'.repeat(44), biller_name: 'Internet' },
        frequency: 'monthly',
        max_executions: 2,
      })
    ).json();

    expect((await run())[0].status).toBe('active');
    expect((await get(id)).executions_count).toBe(1);

    await prisma.scheduledPayment.update({ where: { scheduled_payment_id: id }, data: { next_run_at: new Date(Date.now() - 1000) } });
    expect((await run())[0].status).toBe('completed');
    expect(await balanceOf(CHK)).toBe(980);
  });

  it('diário termina depois do end_date', async () => {
    const today = new Date().toISOString().slice(0, 10);
    (await create(transfer({ frequency: 'daily', end_date: today }))).json();
    expect((await run())[0].status).toBe('completed');
  });

  it('erro de validação na execução é registrado e o agendamento falha', async () => {
    const { scheduled_payment_id: id } = (await create(transfer())).json();
    await prisma.product.delete({ where: { product_id: CHK } });
    const [result] = await run();
    expect(result).toMatchObject({ status: 'failed', transaction_id: null, result: `Erro: Produto ${CHK} não encontrado(a).` });
    expect((await get(id)).last_result).toBe(result.result);
  });

  it('erro inesperado desfaz a execução e retorna 500', async () => {
    await prisma.scheduledPayment.create({
      data: {
        scheduled_payment_id: 'SCH-BROKEN',
        customer_id: ANA,
        product_id: CHK,
        payment_method: 'pix',
        amount: 1,
        currency: 'USD',
        destination: { pix_key: 123 },
        frequency: 'once',
        next_run_at: new Date(),
      },
    });
    const res = await app.inject({ method: 'POST', url: '/api/scheduled-payments/run', headers: SERVICE });
    expect(res.statusCode).toBe(500);
    const row = await prisma.scheduledPayment.findUniqueOrThrow({ where: { scheduled_payment_id: 'SCH-BROKEN' } });
    expect(row).toMatchObject({ status: 'active', executions_count: 0 });
  });

  it('respeita o limite de execuções por chamada', async () => {
    const { runDueSchedules } = await import('../src/services/scheduled.js');
    await create(transfer({ amount: 1 }));
    await create(transfer({ amount: 2 }));
    expect(await runDueSchedules(1)).toHaveLength(1);
    expect(await runDueSchedules()).toHaveLength(1);
  });
});
