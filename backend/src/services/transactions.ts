import { Prisma, prisma, type Decimal } from '../db/prisma.js';
import { LOAN_PRODUCTS, PRODUCT_TYPES, displayNumber, isoDay } from '../lib/domain.js';
import { notFound } from '../lib/errors.js';
import { explainStatus } from '../lib/responseCodes.js';
import { assertCustomer } from './customers.js';

/** Valor em USD: amount_usd, o próprio valor se já for USD, ou a cotação do dia da transação. */
const AMOUNT_USD = Prisma.sql`
  COALESCE(
    t.amount_usd,
    CASE WHEN t.currency = 'USD' THEN t.amount END,
    round(t.amount * (
      SELECT r.exchange_rate FROM daily_exchange_rates r
       WHERE r.source_currency = t.currency AND r.target_currency = 'USD'
         AND r.date <= t.transaction_date::date
       ORDER BY r.date DESC LIMIT 1
    ), 2)
  )`;

const CATEGORY = Prisma.sql`
  COALESCE(
    t.transaction_category,
    t.merchant_category,
    CASE t.transaction_type WHEN 'Withdrawal' THEN 'Withdrawals' WHEN 'Transfer' THEN 'Transfers' ELSE 'Uncategorized' END
  )`;

const DIRECTION = Prisma.sql`
  CASE t.transaction_type WHEN 'Deposit' THEN 'in' WHEN 'Adjustment' THEN 'adjustment' ELSE 'out' END`;

const OUTFLOW_TYPES = ['Purchase', 'Withdrawal', 'Transfer', 'Payment'];

export interface TransactionFilters {
  from?: string;
  to?: string;
  type?: string;
  status?: string;
  category?: string;
  channel?: string;
  product_id?: string;
  origin?: string;
  limit: number;
  offset: number;
}

function buildWhere(customerId: string, f: TransactionFilters): Prisma.Sql {
  const conditions: Prisma.Sql[] = [Prisma.sql`t.customer_id = ${customerId}`];
  if (f.from) conditions.push(Prisma.sql`t.transaction_date >= ${f.from}::date`);
  if (f.to) conditions.push(Prisma.sql`t.transaction_date < ${f.to}::date + interval '1 day'`);
  if (f.type) conditions.push(Prisma.sql`t.transaction_type = ${f.type}`);
  if (f.status) conditions.push(Prisma.sql`t.transaction_status = ${f.status}`);
  if (f.channel) conditions.push(Prisma.sql`t.channel = ${f.channel}`);
  if (f.product_id) conditions.push(Prisma.sql`t.product_id = ${f.product_id}`);
  if (f.origin) conditions.push(Prisma.sql`t.origin = ${f.origin}`);
  if (f.category) conditions.push(Prisma.sql`${CATEGORY} = ${f.category}`);
  return Prisma.join(conditions, ' AND ');
}

const LIST_COLUMNS = Prisma.sql`
  t.transaction_id, t.transaction_date, t.product_id, p.product_type, t.transaction_type,
  ${CATEGORY} AS category, ${DIRECTION} AS direction,
  t.amount, t.currency, ${AMOUNT_USD} AS amount_usd,
  t.channel, t.merchant_name, t.transaction_city, t.transaction_country,
  t.transaction_status, t.response_code, t.origin, t.payment_method, t.description`;

interface ListRow {
  transaction_id: string;
  transaction_status: string | null;
  response_code: string | null;
  [key: string]: unknown;
}

export async function listTransactions(customerId: string, f: TransactionFilters) {
  await assertCustomer(customerId);
  const where = buildWhere(customerId, f);
  const { limit, offset } = f;

  const [items, [{ total }]] = await Promise.all([
    prisma.$queryRaw<ListRow[]>`
      SELECT ${LIST_COLUMNS}
        FROM transactions t LEFT JOIN products p ON p.product_id = t.product_id
       WHERE ${where}
       ORDER BY t.transaction_date DESC, t.transaction_id
       LIMIT ${limit} OFFSET ${offset}`,
    prisma.$queryRaw<{ total: number }[]>`SELECT count(*)::int AS total FROM transactions t WHERE ${where}`,
  ]);

  return {
    total,
    limit,
    offset,
    items: items.map((row) => ({ ...row, status_reason: explainStatus(row.transaction_status, row.response_code).reason })),
  };
}

interface Location {
  channel: string | null;
  merchant: string | null;
  city: string | null;
  branch: { branch_name: string | null; address: string | null; city: string | null } | null;
}

const PHYSICAL_CHANNELS: Record<string, string> = {
  ATM: 'Caixa eletrônico (ATM)',
  Branch: 'Guichê de agência',
  POS: 'Maquininha (POS)',
};

export function describeLocation({ channel, merchant, city, branch }: Location): string {
  const label = PHYSICAL_CHANNELS[channel ?? ''];
  if (!label) return `Canal digital (${channel ?? 'não informado'})`;
  const place = branch ? `agência ${branch.branch_name} — ${branch.address}, ${branch.city}` : (city ?? 'local não informado');
  return `${label}${merchant ? ` em ${merchant}` : ''}: ${place}`;
}

/** Coordenadas perto de (0,0) são inválidas no dataset. */
function coordinates(lat: number | null, lon: number | null) {
  return lat != null && lon != null && (Math.abs(lat) > 1 || Math.abs(lon) > 1) ? { latitude: lat, longitude: lon } : null;
}

/** Detalhe de uma transação, com status explicado (feature 5) e local onde ocorreu (feature 8). */
export async function getTransaction(customerId: string, transactionId: string) {
  const t = await prisma.transaction.findFirst({ where: { customer_id: customerId, transaction_id: transactionId } });
  if (!t) throw notFound('Transação', transactionId);

  const [product, branch] = await Promise.all([
    t.product_id ? prisma.product.findUnique({ where: { product_id: t.product_id } }) : null,
    t.branch_id ? prisma.branch.findUnique({ where: { branch_id: t.branch_id } }) : null,
  ]);

  return {
    transaction_id: t.transaction_id,
    transaction_date: t.transaction_date,
    process_date: isoDay(t.process_date),
    product_id: t.product_id,
    product_type: product?.product_type ?? null,
    transaction_type: t.transaction_type,
    transaction_category: t.transaction_category,
    amount: t.amount,
    currency: t.currency,
    amount_usd: t.amount_usd,
    channel: t.channel,
    merchant_name: t.merchant_name,
    merchant_category: t.merchant_category,
    origin: t.origin,
    payment_method: t.payment_method,
    description: t.description,
    counterparty: t.counterparty,
    related_product_id: t.related_product_id,
    scheduled_payment_id: t.scheduled_payment_id,
    balance_after: t.balance_after,
    flagged_as_fraud: t.is_fraud,
    status: explainStatus(t.transaction_status, t.response_code),
    location: {
      summary: describeLocation({ channel: t.channel, merchant: t.merchant_name, city: t.transaction_city, branch }),
      city: t.transaction_city,
      country: t.transaction_country,
      coordinates: coordinates(t.latitude, t.longitude),
      branch: branch && {
        branch_id: branch.branch_id,
        name: branch.branch_name,
        type: branch.branch_type,
        address: branch.address,
        city: branch.city,
        state: branch.state,
        country: branch.country,
        phone: branch.phone,
        opening_time: branch.opening_time,
        closing_time: branch.closing_time,
        atm_count: branch.atm_count,
        status: branch.branch_status,
        coordinates: coordinates(branch.latitude, branch.longitude),
      },
    },
  };
}

export async function getTransactionStatus(customerId: string, transactionId: string) {
  const t = await prisma.transaction.findFirst({
    where: { customer_id: customerId, transaction_id: transactionId },
    select: {
      transaction_id: true, transaction_date: true, transaction_type: true, amount: true,
      currency: true, transaction_status: true, response_code: true,
    },
  });
  if (!t) throw notFound('Transação', transactionId);
  const { transaction_status, response_code, ...rest } = t;
  return { ...rest, ...explainStatus(transaction_status, response_code) };
}

/**
 * Sem datas, o período padrão são os N dias até a última transação do cliente
 * (o histórico termina em 2026-06-17, então "últimos 30 dias a partir de hoje" viria vazio).
 */
export async function resolvePeriod(customerId: string, from?: string, to?: string, days = 30) {
  let end = to;
  if (!end) {
    const last = await prisma.transaction.aggregate({ where: { customer_id: customerId }, _max: { transaction_date: true } });
    end = (last._max.transaction_date ?? new Date()).toISOString().slice(0, 10);
  }
  const start = from ?? new Date(Date.parse(end) - (days - 1) * 86_400_000).toISOString().slice(0, 10);
  return { from: start, to: end };
}

function periodTx(customerId: string, period: { from: string; to: string }) {
  return Prisma.sql`
    WITH tx AS (
      SELECT t.*, ${CATEGORY} AS category, ${DIRECTION} AS direction, ${AMOUNT_USD} AS usd
        FROM transactions t
       WHERE t.customer_id = ${customerId}
         AND t.transaction_date >= ${period.from}::date
         AND t.transaction_date < ${period.to}::date + interval '1 day'
    )`;
}

/** Feature 6: relatório das transações de um período. */
export async function getReport(customerId: string, opts: { from?: string; to?: string }) {
  await assertCustomer(customerId);
  const period = await resolvePeriod(customerId, opts.from, opts.to);
  const tx = periodTx(customerId, period);

  const [[summary], byType, byStatus, byCategory, byMonth, topMerchants, notCompleted] = await Promise.all([
    prisma.$queryRaw<{ transactions: number; approved: number; inflow_usd: Decimal; outflow_usd: Decimal }[]>`${tx}
      SELECT count(*)::int AS transactions,
             count(*) FILTER (WHERE transaction_status = 'Approved')::int AS approved,
             coalesce(sum(usd) FILTER (WHERE direction = 'in' AND transaction_status = 'Approved'), 0) AS inflow_usd,
             coalesce(sum(usd) FILTER (WHERE direction = 'out' AND transaction_status = 'Approved'), 0) AS outflow_usd
        FROM tx`,
    prisma.$queryRaw`${tx}
      SELECT transaction_type, currency, count(*)::int AS count, sum(amount) AS total_amount, sum(usd) AS total_usd
        FROM tx WHERE transaction_status = 'Approved'
       GROUP BY 1, 2 ORDER BY total_usd DESC NULLS LAST, 1, 2`,
    prisma.$queryRaw`${tx}
      SELECT transaction_status, count(*)::int AS count FROM tx GROUP BY 1 ORDER BY 2 DESC, 1`,
    prisma.$queryRaw`${tx}
      SELECT category, count(*)::int AS count, sum(usd) AS total_usd
        FROM tx WHERE direction = 'out' AND transaction_status = 'Approved'
       GROUP BY 1 ORDER BY total_usd DESC NULLS LAST, 1`,
    prisma.$queryRaw`${tx}
      SELECT to_char(transaction_date, 'YYYY-MM') AS month,
             coalesce(sum(usd) FILTER (WHERE direction = 'in'), 0) AS inflow_usd,
             coalesce(sum(usd) FILTER (WHERE direction = 'out'), 0) AS outflow_usd,
             count(*)::int AS count
        FROM tx WHERE transaction_status = 'Approved'
       GROUP BY 1 ORDER BY 1`,
    prisma.$queryRaw`${tx}
      SELECT merchant_name, count(*)::int AS count, sum(usd) AS total_usd
        FROM tx WHERE merchant_name IS NOT NULL AND transaction_status = 'Approved'
       GROUP BY 1 ORDER BY total_usd DESC NULLS LAST, 1 LIMIT 5`,
    prisma.$queryRaw<ListRow[]>`${tx}
      SELECT transaction_id, transaction_date, transaction_type, amount, currency, transaction_status, response_code
        FROM tx WHERE transaction_status <> 'Approved'
       ORDER BY transaction_date DESC LIMIT 20`,
  ]);

  return {
    customer_id: customerId,
    period,
    currency: 'USD',
    summary: { ...summary, net_usd: summary.inflow_usd.minus(summary.outflow_usd) },
    by_type: byType,
    by_status: byStatus,
    spending_by_category: byCategory,
    by_month: byMonth,
    top_merchants: topMerchants,
    not_completed: notCompleted.map(({ transaction_status, response_code, ...rest }) => ({
      ...rest,
      ...explainStatus(transaction_status, response_code),
    })),
  };
}

/**
 * Feature 7: gastos por categoria, por mês (com variação mês a mês) e por produto/cartão (controle financeiro).
 * Sem `from`, o período são `months` meses-calendário inteiros até `to`, para a tendência comparar meses cheios.
 * `product_id` filtra totais, categorias e meses; `by_product` sempre traz todos os produtos, para comparar.
 */
export async function getSpending(
  customerId: string,
  opts: { from?: string; to?: string; months?: number; product_id?: string },
) {
  await assertCustomer(customerId);
  const resolved = await resolvePeriod(customerId, opts.from, opts.to);
  const period = { from: opts.from ?? firstDayMonthsBack(resolved.to, opts.months ?? 3), to: resolved.to };
  const rows = await prisma.$queryRaw<
    { month: string; category: string; product_id: string | null; product_type: string | null; product_number: string | null; count: number; total_usd: Decimal }[]
  >`
    ${periodTx(customerId, period)}
    SELECT to_char(tx.transaction_date, 'YYYY-MM') AS month, tx.category, tx.product_id, p.product_type, p.product_number,
           count(*)::int AS count, coalesce(sum(tx.usd), 0) AS total_usd
      FROM tx LEFT JOIN products p ON p.product_id = tx.product_id
     WHERE tx.transaction_status = 'Approved' AND tx.transaction_type = ANY(${OUTFLOW_TYPES})
     GROUP BY 1, 2, 3, 4, 5
     ORDER BY 1, 2, 3`;

  const usd = (rs: typeof rows) => rs.reduce((sum, r) => sum + r.total_usd.toNumber(), 0);
  const own = opts.product_id ? rows.filter((r) => r.product_id === opts.product_id) : rows;
  const total = usd(own);
  const allTotal = usd(rows);
  const months = monthsBetween(period.from, period.to);
  const perMonth = (rs: typeof rows) => months.map((month) => round(usd(rs.filter((r) => r.month === month))));

  const categories = [...new Set(own.map((r) => r.category))].map((category) => {
    const cat = own.filter((r) => r.category === category);
    const sum = usd(cat);
    return {
      category,
      count: cat.reduce((n, r) => n + r.count, 0),
      total_usd: round(sum),
      share_pct: round((sum / total) * 100),
      monthly_average_usd: round(sum / months.length),
    };
  });

  const monthTotals = perMonth(own);
  const products = [...new Set(rows.map((r) => r.product_id))].map((productId) => {
    const prod = rows.filter((r) => r.product_id === productId);
    const sum = usd(prod);
    const totals = perMonth(prod);
    return {
      product_id: productId,
      product_type: prod[0].product_type,
      product_number: displayNumber(prod[0].product_type ?? '', prod[0].product_number),
      total_usd: round(sum),
      share_pct: round((sum / allTotal) * 100),
      by_month: months.map((month, i) => ({ month, total_usd: totals[i] })),
    };
  });

  return {
    customer_id: customerId,
    period,
    product_id: opts.product_id ?? null,
    currency: 'USD',
    total_spent_usd: round(total),
    monthly_average_usd: round(total / months.length),
    by_category: categories.sort((a, b) => b.total_usd - a.total_usd),
    by_month: months.map((month, i) => {
      const prev = monthTotals[i - 1];
      return {
        month,
        total_usd: monthTotals[i],
        change_pct: prev ? round(((monthTotals[i] - prev) / prev) * 100) : null,
        categories: Object.fromEntries(own.filter((r) => r.month === month).map((r) => [r.category, r.total_usd])),
      };
    }),
    by_product: products.sort((a, b) => b.total_usd - a.total_usd),
  };
}

/** Primeiro dia do mês, `months - 1` meses antes do mês de `day` (YYYY-MM-DD). */
function firstDayMonthsBack(day: string, months: number) {
  const d = new Date(`${day.slice(0, 7)}-01T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() - (months - 1));
  return d.toISOString().slice(0, 10);
}

/** Meses "YYYY-MM" de `from` a `to`, inclusive (meses sem gasto entram com zero). */
function monthsBetween(from: string, to: string) {
  const out: string[] = [];
  const d = new Date(`${from.slice(0, 7)}-01T00:00:00Z`);
  while (d.toISOString().slice(0, 7) <= to.slice(0, 7)) {
    out.push(d.toISOString().slice(0, 7));
    d.setUTCMonth(d.getUTCMonth() + 1);
  }
  return out;
}

const round = (n: number) => Math.round(n * 100) / 100;

/** Feature 9: ajustes lançados nos produtos (por padrão só empréstimos), com o contexto do produto. */
export async function getAdjustments(customerId: string, opts: { product_id?: string; loans_only: boolean; limit: number }) {
  await assertCustomer(customerId);
  const products = await prisma.product.findMany({
    where: {
      customer_id: customerId,
      product_id: opts.product_id,
      ...(opts.loans_only ? { product_type: { in: LOAN_PRODUCTS } } : {}),
    },
  });
  const byId = new Map(products.map((p) => [p.product_id, p]));
  const adjustments = await prisma.transaction.findMany({
    where: { customer_id: customerId, transaction_type: 'Adjustment', product_id: { in: [...byId.keys()] } },
    orderBy: { transaction_date: 'desc' },
    take: opts.limit,
  });

  return adjustments.map((t) => {
    const p = byId.get(t.product_id!)!;
    return {
      transaction_id: t.transaction_id,
      transaction_date: t.transaction_date,
      amount: t.amount,
      currency: t.currency,
      channel: t.channel,
      ...explainStatus(t.transaction_status, t.response_code),
      product: {
        product_id: p.product_id,
        product_type: p.product_type,
        status: p.product_status,
        outstanding_balance: p.current_balance,
        interest_rate: p.interest_rate,
        days_past_due: p.days_past_due,
        expiration_date: isoDay(p.expiration_date),
      },
      explanation: explainAdjustment(p.product_type, p.days_past_due),
    };
  });
}

const ADJUSTMENT_EXPLANATIONS: Record<string, string> = {
  [PRODUCT_TYPES.investment]: 'Ajuste no investimento: rendimento creditado ou correção de valor.',
  [PRODUCT_TYPES.insurance]: 'Ajuste no seguro: correção do prêmio ou da cobertura.',
};

export function explainAdjustment(productType: string, daysPastDue: number | null): string {
  if (!LOAN_PRODUCTS.includes(productType)) {
    return ADJUSTMENT_EXPLANATIONS[productType] ?? `Ajuste lançado no produto ${productType}.`;
  }
  const late = daysPastDue
    ? ` O produto tem ${daysPastDue} dia(s) de atraso, o que gera juros de mora e encargos.`
    : '';
  return `Ajuste no ${productType}: correção de saldo por juros, encargos, recálculo de parcelas ou estorno.${late}`;
}
