import { prisma, type Prisma } from '../db/prisma.js';
import type { ScheduledPayment } from '../generated/prisma/client.js';
import { isoDay } from '../lib/domain.js';
import { AppError, notFound, unprocessable } from '../lib/errors.js';
import { newId } from '../lib/ids.js';
import { assertCustomer } from './customers.js';
import { executeWithClient, validateRequest, type Destination, type PaymentMethod } from './payments.js';

export type Frequency = 'once' | 'daily' | 'weekly' | 'monthly';

export interface CreateScheduleInput {
  source_product_id: string;
  method: PaymentMethod;
  amount: number;
  currency?: string;
  destination: Destination;
  description?: string;
  frequency: Frequency;
  start_at?: string;
  end_date?: string;
  max_executions?: number;
}

export interface UpdateScheduleInput {
  status?: 'active' | 'paused';
  amount?: number;
  next_run_at?: string;
  end_date?: string;
  description?: string;
}

const CLOSED = ['cancelled', 'completed', 'failed'];

export function nextRun(from: Date, frequency: Frequency): Date | null {
  const d = new Date(from);
  if (frequency === 'once') return null;
  if (frequency === 'daily') d.setUTCDate(d.getUTCDate() + 1);
  if (frequency === 'weekly') d.setUTCDate(d.getUTCDate() + 7);
  if (frequency === 'monthly') {
    // Mantém o dia; se o mês seguinte for mais curto, usa o último dia (31/01 -> 28/02).
    const day = d.getUTCDate();
    d.setUTCDate(1);
    d.setUTCMonth(d.getUTCMonth() + 1);
    const lastDay = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
    d.setUTCDate(Math.min(day, lastDay));
  }
  return d;
}

function present(row: ScheduledPayment) {
  return { ...row, end_date: isoDay(row.end_date) };
}

export async function createSchedule(customerId: string, input: CreateScheduleInput) {
  await assertCustomer(customerId);
  const startAt = input.start_at ? new Date(input.start_at) : new Date();
  if (startAt.getTime() < Date.now() - 60_000) {
    throw unprocessable('invalid_start_at', 'start_at não pode estar no passado.');
  }
  if (input.end_date && input.end_date < startAt.toISOString().slice(0, 10)) {
    throw unprocessable('invalid_end_date', 'end_date não pode ser anterior ao início.');
  }

  const { currency } = await validateRequest(prisma, {
    customerId,
    sourceProductId: input.source_product_id,
    method: input.method,
    amount: input.amount,
    currency: input.currency,
    destination: input.destination,
  });

  const row = await prisma.scheduledPayment.create({
    data: {
      scheduled_payment_id: newId('SCH', 16),
      customer_id: customerId,
      product_id: input.source_product_id,
      payment_method: input.method,
      amount: input.amount,
      currency,
      destination: input.destination as Prisma.InputJsonObject,
      description: input.description,
      frequency: input.frequency,
      next_run_at: startAt,
      end_date: input.end_date ? new Date(input.end_date) : null,
      max_executions: input.frequency === 'once' ? 1 : input.max_executions,
    },
  });
  return { ...present(row), executions: [] };
}

export async function listSchedules(customerId: string, status?: string) {
  await assertCustomer(customerId);
  const rows = await prisma.scheduledPayment.findMany({
    where: { customer_id: customerId, status },
    orderBy: [{ next_run_at: { sort: 'asc', nulls: 'last' } }, { created_at: 'desc' }],
  });
  return rows.map(present);
}

export async function getSchedule(customerId: string, id: string) {
  const row = await prisma.scheduledPayment.findFirst({ where: { customer_id: customerId, scheduled_payment_id: id } });
  if (!row) throw notFound('Agendamento', id);
  const executions = await prisma.transaction.findMany({
    where: { scheduled_payment_id: id, customer_id: customerId },
    select: { transaction_id: true, transaction_date: true, amount: true, currency: true, transaction_status: true, response_code: true },
    orderBy: { transaction_date: 'desc' },
    take: 50,
  });
  return { ...present(row), executions };
}

async function getOpenSchedule(customerId: string, id: string) {
  const current = await getSchedule(customerId, id);
  if (CLOSED.includes(current.status)) {
    throw new AppError(409, 'schedule_closed', `O agendamento está ${current.status} e não pode ser alterado.`);
  }
  return current;
}

export async function updateSchedule(customerId: string, id: string, patch: UpdateScheduleInput) {
  await getOpenSchedule(customerId, id);
  await prisma.scheduledPayment.update({
    where: { scheduled_payment_id: id },
    data: {
      status: patch.status,
      amount: patch.amount,
      next_run_at: patch.next_run_at ? new Date(patch.next_run_at) : undefined,
      end_date: patch.end_date ? new Date(patch.end_date) : undefined,
      description: patch.description,
    },
  });
  return getSchedule(customerId, id);
}

export async function cancelSchedule(customerId: string, id: string) {
  await getOpenSchedule(customerId, id);
  await prisma.scheduledPayment.update({
    where: { scheduled_payment_id: id },
    data: { status: 'cancelled', next_run_at: null },
  });
  return getSchedule(customerId, id);
}

async function runOne(tx: Prisma.TransactionClient, row: ScheduledPayment) {
  let transactionId: string | null = null;
  let approved = false;
  let result: string;

  // Se a validação falhar (ex.: produto removido), desfaz só a tentativa e registra o erro.
  await tx.$executeRaw`SAVEPOINT run_schedule`;
  try {
    const payment = await executeWithClient(tx, {
      customerId: row.customer_id,
      sourceProductId: row.product_id,
      method: row.payment_method as PaymentMethod,
      amount: row.amount.toNumber(),
      currency: row.currency,
      destination: row.destination as Destination,
      description: row.description ?? `Pagamento agendado ${row.scheduled_payment_id}`,
      scheduledPaymentId: row.scheduled_payment_id,
    });
    transactionId = payment.transaction_id;
    approved = payment.completed;
    result = approved ? 'Approved' : `Declined (${payment.response_code}): ${payment.decline_detail}`;
  } catch (err) {
    await tx.$executeRaw`ROLLBACK TO SAVEPOINT run_schedule`;
    if (!(err instanceof AppError)) throw err;
    result = `Erro: ${err.message}`;
  }

  const executions = row.executions_count + 1;
  const next = nextRun(row.next_run_at!, row.frequency as Frequency);
  const finished =
    next == null ||
    (row.max_executions != null && executions >= row.max_executions) ||
    (row.end_date != null && next > new Date(row.end_date.getTime() + 86_400_000));
  const status = !finished ? 'active' : row.frequency === 'once' && !approved ? 'failed' : 'completed';

  await tx.scheduledPayment.update({
    where: { scheduled_payment_id: row.scheduled_payment_id },
    data: {
      executions_count: executions,
      last_run_at: new Date(),
      last_transaction_id: transactionId,
      last_result: result,
      next_run_at: finished ? null : next,
      status,
    },
  });
  return { scheduled_payment_id: row.scheduled_payment_id, transaction_id: transactionId, result, status };
}

/** Executa os agendamentos vencidos, um por transação. Seguro com várias instâncias (SKIP LOCKED). */
export async function runDueSchedules(limit = 100) {
  const results = [];
  while (results.length < limit) {
    const outcome = await prisma.$transaction(async (tx) => {
      const [due] = await tx.$queryRaw<{ scheduled_payment_id: string }[]>`
        SELECT scheduled_payment_id FROM scheduled_payments
         WHERE status = 'active' AND next_run_at <= now()
         ORDER BY next_run_at
         LIMIT 1
         FOR UPDATE SKIP LOCKED`;
      if (!due) return null;
      const row = await tx.scheduledPayment.findUniqueOrThrow({ where: { scheduled_payment_id: due.scheduled_payment_id } });
      return runOne(tx, row);
    });
    if (!outcome) break;
    results.push(outcome);
  }
  return results;
}
