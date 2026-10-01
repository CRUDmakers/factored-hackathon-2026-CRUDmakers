import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { prisma } from '../src/db/prisma.js';
import { ANA, BARCODE, UNKNOWN, ownerApp, resetData } from './helpers.js';

let app: FastifyInstance;
beforeAll(async () => {
  app = await ownerApp();
});
beforeEach(resetData);
afterAll(() => app.close());

const CHK = 'PRD-ANACHK000001';
const TO_BRUNO = { source_product_id: CHK, amount: 100, to_product_id: 'PRD-BRUCHK000001', description: 'aluguel' };
const BILL = { source_product_id: CHK, amount: 30, barcode: BARCODE, biller_name: 'Luz' };

/** Faz o pagamento pela API e muda a data dele, como se tivesse sido feito em `date`. */
async function pay(path: string, payload: object, date: string) {
  const res = await app.inject({ method: 'POST', url: `/api/customers/${ANA}/${path}`, payload });
  expect(res.statusCode).toBe(201);
  const id = res.json().transaction_id as string;
  await prisma.transaction.update({ where: { transaction_id: id }, data: { transaction_date: new Date(date) } });
  return id;
}

const recurring = async (asOf?: string, customer = ANA) =>
  app.inject(`/api/customers/${customer}/recurring-payments${asOf ? `?as_of=${asOf}` : ''}`);
const items = async (asOf: string) => (await recurring(asOf)).json().items;

describe('pagamentos recorrentes mensais', () => {
  it('identifica o mesmo pagamento em 2 meses seguidos e diz se já foi pago no mês', async () => {
    await pay('transfers', TO_BRUNO, '2026-08-10T12:00:00Z');
    const last = await pay('transfers', TO_BRUNO, '2026-09-10T12:00:00Z');

    const paid = (await recurring('2026-09-20')).json();
    expect(paid).toMatchObject({ customer_id: ANA, as_of: '2026-09-20', month: '2026-09', summary: { recurring: 1, due: 0, due_totals: [] } });
    expect(paid.items).toEqual([
      {
        recurring_id: expect.stringMatching(/^REC-[0-9A-F]{16}$/),
        method: 'transfer',
        destination_type: 'internal',
        recipient: 'Bruno Gómez',
        amount: 100,
        currency: 'USD',
        source_product_id: CHK,
        description: 'aluguel',
        months: ['2026-08', '2026-09'],
        consecutive_months: 2,
        last_paid_at: '2026-09-10T12:00:00.000Z',
        last_transaction_id: last,
        due_date: '2026-09-10',
        next_due_date: '2026-10-10',
        status: 'paid',
        overdue: false,
        scheduled_payment_id: null,
        payment: {
          method: 'transfer',
          source_product_id: CHK,
          amount: 100,
          currency: 'USD',
          description: 'aluguel',
          destination: { to_product_id: 'PRD-BRUCHK000001' },
        },
      },
    ]);

    const [due] = await items('2026-10-05');
    expect(due).toMatchObject({ status: 'due', overdue: false, due_date: '2026-10-10', next_due_date: '2026-10-10', recurring_id: paid.items[0].recurring_id });
    const [late] = await items('2026-10-20');
    expect(late).toMatchObject({ status: 'due', overdue: true });
  });

  it('soma o que falta pagar por moeda e ordena pelo vencimento', async () => {
    for (const month of ['07', '08']) {
      await pay('transfers', TO_BRUNO, `2026-${month}-10T12:00:00Z`);
      await pay('bill-payments', BILL, `2026-${month}-10T09:00:00Z`);
      await pay('bill-payments', { ...BILL, biller_name: undefined, amount: 5 }, `2026-${month}-05T09:00:00Z`);
    }
    const body = (await recurring('2026-09-01')).json();
    expect(body.summary).toEqual({ recurring: 3, due: 3, due_totals: [{ currency: 'USD', amount: 135 }] });
    expect(body.items.map((i: { next_due_date: string }) => i.next_due_date)).toEqual(['2026-09-05', '2026-09-10', '2026-09-10']);
    expect(body.items.map((i: { recipient: string | null }) => i.recipient).slice(1).sort()).toEqual(['Bruno Gómez', 'Luz']);
    expect(body.items[0].recipient).toBeNull();
    const bill = body.items.find((i: { recipient: string | null }) => i.recipient === 'Luz');
    expect(bill).toMatchObject({ method: 'bill_payment', destination_type: 'bill', payment: { destination: { barcode: BARCODE, biller_name: 'Luz' } } });
    expect(body.items[0].payment.destination).toEqual({ barcode: BARCODE });
  });

  it('o corpo de `payment` paga de novo o mesmo destino', async () => {
    const beneficiary = { name: 'Luis', account_number: '123', country: 'Mexico' };
    await pay('transfers', { source_product_id: CHK, amount: 20, beneficiary }, '2026-08-03T12:00:00Z');
    await pay('transfers', { source_product_id: CHK, amount: 20, beneficiary }, '2026-09-03T12:00:00Z');
    await pay('pix', { source_product_id: CHK, amount: 25, pix_key: 'DOC-BRUNO' }, '2026-08-04T12:00:00Z');
    await pay('pix', { source_product_id: CHK, amount: 25, pix_key: 'DOC-BRUNO' }, '2026-09-04T12:00:00Z');

    const found = await items('2026-09-30');
    expect(found.map((i: { destination_type: string; recipient: string }) => [i.destination_type, i.recipient])).toEqual([
      ['external', 'Luis'],
      ['pix', 'Bruno Gómez'],
    ]);
    expect(found[0].payment.destination).toEqual({ beneficiary: { name: 'Luis', account_number: '123', country: 'México' } });
    expect(found[0].payment.description).toBeUndefined();

    for (const { payment } of found) {
      const { method, destination, ...common } = payment;
      const path = { transfer: 'transfers', pix: 'pix' }[method as 'transfer' | 'pix'];
      const res = await app.inject({ method: 'POST', url: `/api/customers/${ANA}/${path}`, payload: { ...common, ...destination } });
      expect(res.json()).toMatchObject({ completed: true, method });
    }
  });

  it('ignora o que não se repete em meses seguidos ou deixou de ser pago', async () => {
    await pay('transfers', TO_BRUNO, '2026-06-10T12:00:00Z'); // jun + jul: parou antes de agosto
    await pay('transfers', TO_BRUNO, '2026-07-10T12:00:00Z');
    await pay('transfers', { ...TO_BRUNO, amount: 50 }, '2026-07-10T12:00:00Z'); // jul e set: pulou agosto
    await pay('transfers', { ...TO_BRUNO, amount: 50 }, '2026-09-10T12:00:00Z');
    await pay('transfers', { ...TO_BRUNO, amount: 70 }, '2026-09-11T12:00:00Z'); // só um mês
    await pay('transfers', { ...TO_BRUNO, amount: 70 }, '2026-09-12T12:00:00Z');
    await pay('transfers', { ...TO_BRUNO, amount: 99 }, '2026-08-10T12:00:00Z'); // valores diferentes
    await pay('transfers', { ...TO_BRUNO, amount: 98 }, '2026-09-10T12:00:00Z');
    await pay('transfers', { ...TO_BRUNO, amount: 10 }, '2026-08-10T12:00:00Z'); // depois do mês avaliado
    await pay('transfers', { ...TO_BRUNO, amount: 10 }, '2026-10-10T12:00:00Z');
    expect(await items('2026-09-15')).toEqual([]);
  });

  it('pagamento coberto por agendamento ativo não aparece como pendente', async () => {
    const ids = [await pay('transfers', TO_BRUNO, '2026-08-10T12:00:00Z'), await pay('transfers', TO_BRUNO, '2026-09-10T12:00:00Z')];
    const schedule = (
      await app.inject({
        method: 'POST',
        url: `/api/customers/${ANA}/scheduled-payments`,
        payload: { source_product_id: CHK, method: 'transfer', amount: 100, destination: { to_product_id: 'PRD-BRUCHK000001' }, frequency: 'monthly', start_at: '2099-01-10T12:00:00Z' },
      })
    ).json();
    await prisma.transaction.updateMany({ where: { transaction_id: { in: ids } }, data: { scheduled_payment_id: schedule.scheduled_payment_id } });

    const body = (await recurring('2026-10-20')).json();
    expect(body.items[0]).toMatchObject({ status: 'scheduled', overdue: false, scheduled_payment_id: schedule.scheduled_payment_id });
    expect(body.summary).toMatchObject({ recurring: 1, due: 0 });
  });

  it('vencimento no fim do mês respeita meses mais curtos', async () => {
    await pay('transfers', TO_BRUNO, '2026-12-31T12:00:00Z');
    await pay('transfers', TO_BRUNO, '2027-01-31T12:00:00Z');
    const [item] = await items('2027-02-01');
    expect(item).toMatchObject({ months: ['2026-12', '2027-01'], due_date: '2027-02-28', next_due_date: '2027-02-28' });
  });

  it('sem as_of usa o mês de hoje', async () => {
    const now = new Date();
    const previous = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1, 12));
    await pay('transfers', TO_BRUNO, previous.toISOString());
    await pay('transfers', TO_BRUNO, new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1, 12)).toISOString());
    const body = (await recurring()).json();
    expect(body.as_of).toBe(now.toISOString().slice(0, 10));
    expect(body.items[0].status).toBe('paid');
  });

  it('404 para cliente inexistente e 400 para data inválida', async () => {
    expect((await recurring(undefined, UNKNOWN)).statusCode).toBe(404);
    expect((await recurring('2026-13-01')).statusCode).toBe(400);
  });
});
