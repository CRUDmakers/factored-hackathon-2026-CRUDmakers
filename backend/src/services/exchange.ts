import { Decimal, prisma, type Db } from '../db/prisma.js';
import { isoDay } from '../lib/domain.js';
import { AppError } from '../lib/errors.js';

export interface ExchangeRate {
  source_currency: string;
  target_currency: string;
  /** Data da cotação usada: a mais recente até a data pedida (o histórico termina em 2026-06-17). */
  rate_date: string | null;
  exchange_rate: Decimal;
  buy_rate: Decimal | null;
  sell_rate: Decimal | null;
  source: string | null;
}

export async function getRate(from: string, to: string, date?: string, db: Db = prisma): Promise<ExchangeRate> {
  from = from.toUpperCase();
  to = to.toUpperCase();
  if (from === to) {
    const one = new Decimal(1);
    return { source_currency: from, target_currency: to, rate_date: null, exchange_rate: one, buy_rate: one, sell_rate: one, source: null };
  }

  const row = await db.dailyExchangeRate.findFirst({
    where: { source_currency: from, target_currency: to, ...(date ? { date: { lte: new Date(date) } } : {}) },
    orderBy: { date: 'desc' },
  });
  if (!row) {
    throw new AppError(404, 'rate_not_found', `Não há cotação de ${from} para ${to}${date ? ` até ${date}` : ''}.`);
  }
  return {
    source_currency: from,
    target_currency: to,
    rate_date: isoDay(row.date),
    exchange_rate: row.exchange_rate,
    buy_rate: row.buy_rate,
    sell_rate: row.sell_rate,
    source: row.source,
  };
}

export async function convert(amount: Decimal | number, from: string, to: string, date?: string, db: Db = prisma) {
  const rate = await getRate(from, to, date, db);
  const value = new Decimal(amount);
  return {
    amount: value,
    converted_amount: value.times(rate.exchange_rate).toDecimalPlaces(2),
    rate,
  };
}

export async function getRateHistory(from: string, to: string, startDate: string, endDate: string) {
  const rows = await prisma.dailyExchangeRate.findMany({
    where: {
      source_currency: from.toUpperCase(),
      target_currency: to.toUpperCase(),
      date: { gte: new Date(startDate), lte: new Date(endDate) },
    },
    orderBy: { date: 'asc' },
  });
  return rows.map((r) => ({ ...r, date: isoDay(r.date) }));
}

export async function getAvailablePairs() {
  const rows = await prisma.dailyExchangeRate.groupBy({
    by: ['source_currency', 'target_currency'],
    _min: { date: true },
    _max: { date: true },
    orderBy: [{ source_currency: 'asc' }, { target_currency: 'asc' }],
  });
  return rows.map((r) => ({
    source_currency: r.source_currency,
    target_currency: r.target_currency,
    first_date: isoDay(r._min.date),
    last_date: isoDay(r._max.date),
  }));
}
