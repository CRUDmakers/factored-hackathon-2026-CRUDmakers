import { Decimal, prisma, type Db } from '../db/prisma.js';
import type { Product } from '../generated/prisma/client.js';
import { DEBT_PRODUCTS, FUNDS_PRODUCTS, LOAN_PRODUCTS, PRODUCT_TYPES, displayNumber, isoDay, maskNumber, round2, today } from '../lib/domain.js';
import { notFound } from '../lib/errors.js';
import { getRate } from './exchange.js';

export async function getCustomer(customerId: string) {
  const customer = await prisma.customer.findUnique({
    where: { customer_id: customerId },
    select: {
      customer_id: true, document_type: true, first_name: true, last_name: true, email: true,
      mobile_phone: true, city: true, state: true, country: true, segment: true,
      customer_status: true, registration_date: true,
    },
  });
  if (!customer) throw notFound('Cliente', customerId);
  return customer;
}

export async function assertCustomer(customerId: string, db: Db = prisma): Promise<void> {
  const found = await db.customer.count({ where: { customer_id: customerId } });
  if (!found) throw notFound('Cliente', customerId);
}

/** Formato público de um produto: número mascarado, datas sem hora e campos derivados. */
export function presentProduct(p: Product) {
  const expiration = isoDay(p.expiration_date);
  return {
    product_id: p.product_id,
    product_type: p.product_type,
    product_number: displayNumber(p.product_type, p.product_number),
    currency: p.currency,
    status: p.product_status,
    current_balance: p.current_balance,
    credit_limit: p.credit_limit,
    available_credit: p.credit_limit ? p.credit_limit.minus(p.current_balance ?? 0) : null,
    interest_rate: p.interest_rate,
    opening_date: isoDay(p.opening_date),
    expiration_date: expiration,
    is_expired: expiration != null && expiration < today(),
    days_past_due: p.days_past_due,
    last_transaction_date: p.last_transaction_date,
  };
}

export async function listProducts(customerId: string, filters: { type?: string; status?: string } = {}) {
  await assertCustomer(customerId);
  return prisma.product.findMany({
    where: { customer_id: customerId, product_type: filters.type, product_status: filters.status },
    orderBy: [{ product_type: 'asc' }, { product_id: 'asc' }],
  });
}

export async function getProduct(customerId: string, productId: string, db: Db = prisma): Promise<Product> {
  const product = await db.product.findFirst({ where: { product_id: productId, customer_id: customerId } });
  if (!product) throw notFound('Produto', productId);
  return product;
}

/** Feature 1: quanto dinheiro o cliente tem (contas) e deve (cartões e empréstimos). */
export async function getBalances(customerId: string) {
  const products = (await listProducts(customerId)).filter((p) => p.product_status !== 'Closed');
  const balance = (p: Product) => p.current_balance ?? new Decimal(0);
  const ofType = (types: string[]) => products.filter((p) => types.includes(p.product_type));

  const accounts = ofType(FUNDS_PRODUCTS).map((p) => ({
    product_id: p.product_id,
    product_type: p.product_type,
    product_number: displayNumber(p.product_type, p.product_number),
    currency: p.currency,
    status: p.product_status,
    balance: balance(p),
  }));

  const creditCards = ofType([PRODUCT_TYPES.creditCard]).map((p) => {
    const limit = p.credit_limit ?? new Decimal(0);
    return {
      product_id: p.product_id,
      product_number: maskNumber(p.product_number),
      currency: p.currency,
      status: p.product_status,
      invoice_amount: balance(p),
      credit_limit: limit,
      available_credit: limit.minus(balance(p)),
      utilization_pct: limit.isZero() ? null : round2(balance(p).div(limit).times(100).toNumber()),
      interest_rate: p.interest_rate,
      expiration_date: isoDay(p.expiration_date),
      days_past_due: p.days_past_due,
    };
  });

  const loans = ofType(LOAN_PRODUCTS).map((p) => ({
    product_id: p.product_id,
    product_type: p.product_type,
    currency: p.currency,
    status: p.product_status,
    outstanding_balance: balance(p),
    interest_rate: p.interest_rate,
    expiration_date: isoDay(p.expiration_date),
    days_past_due: p.days_past_due,
  }));

  const investments = ofType([PRODUCT_TYPES.investment]).map((p) => ({
    product_id: p.product_id,
    currency: p.currency,
    status: p.product_status,
    balance: balance(p),
    interest_rate: p.interest_rate,
    expiration_date: isoDay(p.expiration_date),
  }));

  // Totais por moeda e patrimônio líquido aproximado em USD (cotação mais recente).
  const byCurrency = new Map<string, { available: Decimal; debt: Decimal; investments: Decimal }>();
  for (const p of products) {
    const zero = new Decimal(0);
    const bucket = byCurrency.get(p.currency) ?? { available: zero, debt: zero, investments: zero };
    if (FUNDS_PRODUCTS.includes(p.product_type)) bucket.available = bucket.available.plus(balance(p));
    if (DEBT_PRODUCTS.includes(p.product_type)) bucket.debt = bucket.debt.plus(balance(p));
    if (p.product_type === PRODUCT_TYPES.investment) bucket.investments = bucket.investments.plus(balance(p));
    byCurrency.set(p.currency, bucket);
  }

  let netWorthUsd = new Decimal(0);
  const totals = [];
  for (const [currency, t] of byCurrency) {
    const net = t.available.plus(t.investments).minus(t.debt);
    const rate = await getRate(currency, 'USD');
    netWorthUsd = netWorthUsd.plus(net.times(rate.exchange_rate));
    totals.push({ currency, available_funds: t.available, investments: t.investments, debt: t.debt, net, usd_rate: rate.exchange_rate, usd_rate_date: rate.rate_date });
  }

  return {
    customer_id: customerId,
    accounts,
    credit_cards: creditCards,
    loans,
    investments,
    totals_by_currency: totals,
    net_worth_usd: netWorthUsd.toDecimalPlaces(2),
  };
}
