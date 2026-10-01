import { createHash } from 'node:crypto';
import { prisma } from '../db/prisma.js';
import type { Transaction } from '../generated/prisma/client.js';
import { isoDay, round2, today } from '../lib/domain.js';
import { assertCustomer } from './customers.js';

/** Quantos meses antes do mês de referência entram na busca. */
const MONTHS_BACK = 12;

type Counterparty = Record<string, unknown>;

const monthIndex = (d: Date) => d.getUTCFullYear() * 12 + d.getUTCMonth();
const monthLabel = (i: number) => `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`;
const monthStart = (i: number) => new Date(Date.UTC(Math.floor(i / 12), i % 12, 1));

/** O mesmo dia do mês em outro mês, limitado ao último dia dele (31/jan → 28/fev). */
function sameDayIn(month: number, day: number): string {
  const lastDay = new Date(Date.UTC(Math.floor(month / 12), (month % 12) + 1, 0)).getUTCDate();
  return isoDay(new Date(Date.UTC(Math.floor(month / 12), month % 12, Math.min(day, lastDay))))!;
}

const withoutNulls = (obj: Record<string, unknown>) => Object.fromEntries(Object.entries(obj).filter(([, v]) => v != null));

/** Destino no formato de `destination` dos agendamentos e nome de quem recebe, a partir do counterparty gravado. */
function destinationOf(cp: Counterparty): { destination: Record<string, unknown>; recipient: string | null } {
  switch (cp.type) {
    case 'bill':
      return { destination: withoutNulls({ barcode: cp.barcode, biller_name: cp.biller_name }), recipient: cp.biller_name as string | null };
    case 'pix':
      return { destination: { pix_key: cp.pix_key }, recipient: cp.recipient_name as string };
    case 'external': {
      const { name, account_number, bank_name, document_number, country } = cp;
      return { destination: { beneficiary: withoutNulls({ name, account_number, bank_name, document_number, country }) }, recipient: name as string };
    }
    default:
      return { destination: { to_product_id: cp.to_product_id }, recipient: cp.recipient_name as string | null };
  }
}

/**
 * Pagamentos recorrentes mensais: operações feitas pela API (transferência, Pix, boleto) para o mesmo destino,
 * com o mesmo valor e moeda, em pelo menos 2 meses seguidos. Entram só as que continuam em dia: pagas no mês
 * de referência ou no anterior. O histórico do dataset não guarda o destino dos pagamentos, então não entra.
 */
export async function getRecurringPayments(customerId: string, opts: { as_of?: string }) {
  await assertCustomer(customerId);
  const asOf = opts.as_of ?? today();
  const reference = monthIndex(new Date(asOf));

  const rows = await prisma.transaction.findMany({
    where: {
      customer_id: customerId,
      origin: 'simulated',
      transaction_status: 'Approved',
      transaction_type: { in: ['Payment', 'Transfer'] },
      payment_method: { not: null },
      transaction_date: { gte: monthStart(reference - MONTHS_BACK), lt: monthStart(reference + 1) },
    },
    orderBy: [{ transaction_date: 'asc' }, { transaction_id: 'asc' }],
  });

  const groups = new Map<string, { destination: Record<string, unknown>; recipient: string | null; rows: Transaction[] }>();
  for (const t of rows) {
    const { destination, recipient } = destinationOf(t.counterparty as Counterparty);
    const key = JSON.stringify([t.payment_method, destination, t.amount.toFixed(2), t.currency]);
    const group = groups.get(key) ?? { destination, recipient, rows: [] };
    group.rows.push(t);
    groups.set(key, group);
  }

  const activeSchedules = new Set(
    (
      await prisma.scheduledPayment.findMany({
        where: { customer_id: customerId, status: 'active' },
        select: { scheduled_payment_id: true },
      })
    ).map((s) => s.scheduled_payment_id),
  );

  const items = [...groups].flatMap(([key, { destination, recipient, rows: own }]) => {
    const months = [...new Set(own.map((t) => monthIndex(t.transaction_date)))];
    const last = months.at(-1)!;
    let streak = 1;
    while (months.at(-1 - streak) === last - streak) streak++;
    if (streak < 2 || last < reference - 1) return [];

    const latest = own.at(-1)!;
    const paid = last === reference;
    const day = latest.transaction_date.getUTCDate();
    // due_date: quando é previsto no mês de referência (para os já pagos, o dia em que foi pago).
    const dueDate = sameDayIn(reference, day);
    const nextDue = paid ? sameDayIn(reference + 1, day) : dueDate;
    const scheduleId = own.map((t) => t.scheduled_payment_id).find((id) => id != null && activeSchedules.has(id)) ?? null;
    return [
      {
        recurring_id: `REC-${createHash('sha256').update(key).digest('hex').slice(0, 16).toUpperCase()}`,
        method: latest.payment_method,
        destination_type: (latest.counterparty as Counterparty).type,
        recipient,
        amount: latest.amount,
        currency: latest.currency,
        source_product_id: latest.product_id,
        description: latest.description,
        months: months.slice(-streak).map(monthLabel),
        consecutive_months: streak,
        last_paid_at: latest.transaction_date,
        last_transaction_id: latest.transaction_id,
        due_date: dueDate,
        next_due_date: nextDue,
        // paid: já pago no mês de referência; scheduled: um agendamento ativo vai pagar; due: falta pagar.
        status: paid ? 'paid' : scheduleId ? 'scheduled' : 'due',
        overdue: !paid && !scheduleId && nextDue < asOf,
        scheduled_payment_id: scheduleId,
        // Corpo pronto para pagar de novo (mesmo formato de method + destination dos agendamentos).
        payment: withoutNulls({
          method: latest.payment_method,
          source_product_id: latest.product_id,
          amount: latest.amount,
          currency: latest.currency,
          description: latest.description,
          destination,
        }),
      },
    ];
  });

  const due = items.filter((i) => i.status === 'due');
  const totals = new Map<string, number>();
  for (const i of due) totals.set(i.currency, round2((totals.get(i.currency) ?? 0) + i.amount.toNumber()));

  return {
    customer_id: customerId,
    as_of: asOf,
    month: monthLabel(reference),
    items: items.sort((a, b) => a.due_date.localeCompare(b.due_date) || a.recurring_id.localeCompare(b.recurring_id)),
    summary: {
      recurring: items.length,
      due: due.length,
      due_totals: [...totals].map(([currency, amount]) => ({ currency, amount })),
    },
  };
}
