import { Decimal, Prisma, prisma, type Db } from '../db/prisma.js';
import type { Product } from '../generated/prisma/client.js';
import {
  BANK_COUNTRIES,
  CARD_PRODUCTS,
  COUNTRY_CURRENCY,
  DEBT_PRODUCTS,
  FUNDS_PRODUCTS,
  PRODUCT_TYPES,
  isoDay,
  today,
  toBankCountry,
  type BankCountry,
} from '../lib/domain.js';
import { unprocessable } from '../lib/errors.js';
import { newId } from '../lib/ids.js';
import { explainStatus, type ResponseCode } from '../lib/responseCodes.js';
import { getProduct } from './customers.js';
import { convert } from './exchange.js';

export type PaymentMethod = 'transfer' | 'pix' | 'bill_payment';

export interface Beneficiary {
  name: string;
  account_number: string;
  bank_name?: string;
  country: string;
  document_number?: string;
}

export interface Destination {
  /** transfer: produto de destino no próprio banco pelo ID interno (ex.: pagar a fatura do próprio cartão). */
  to_product_id?: string;
  /** transfer: número da conta corrente/poupança de outra pessoa no próprio banco. */
  to_account_number?: string;
  /** transfer: conta em outro banco. */
  beneficiary?: Beneficiary;
  /** pix: e-mail, celular ou documento do destinatário. */
  pix_key?: string;
  /** bill_payment: código de barras / linha digitável do boleto. */
  barcode?: string;
  biller_name?: string;
  due_date?: string;
}

export interface PaymentRequest {
  customerId: string;
  sourceProductId: string;
  method: PaymentMethod;
  amount: number;
  currency?: string;
  description?: string;
  category?: string;
  destination: Destination;
  scheduledPaymentId?: string;
}

const SOURCE_TYPES: Record<PaymentMethod, string[]> = {
  transfer: FUNDS_PRODUCTS,
  pix: FUNDS_PRODUCTS,
  bill_payment: [...FUNDS_PRODUCTS, PRODUCT_TYPES.creditCard],
};

const digits = (value: string) => value.replace(/\D/g, '');

/** Validação estrutural (sem checar saldo), usada na execução e ao criar agendamentos. */
export async function validateRequest(db: Db, req: PaymentRequest): Promise<{ source: Product; currency: string }> {
  const source = await getProduct(req.customerId, req.sourceProductId, db);
  if (!SOURCE_TYPES[req.method].includes(source.product_type)) {
    throw unprocessable('invalid_source_product', `Um(a) ${source.product_type} não pode ser usado(a) para ${req.method}.`, {
      allowed_product_types: SOURCE_TYPES[req.method],
    });
  }

  // Valor positivo e moeda suportada já são garantidos pelo schema da rota.
  const currency = req.currency ?? source.currency;

  const d = req.destination;
  if (req.method === 'transfer') {
    if ([d.to_product_id, d.to_account_number, d.beneficiary].filter(Boolean).length !== 1) {
      throw unprocessable(
        'invalid_destination',
        'Informe um destino: to_account_number (conta de outra pessoa no banco), to_product_id (produto no banco) ou beneficiary (outro banco).',
      );
    }
    if (d.to_product_id === source.product_id) {
      throw unprocessable('invalid_destination', 'O produto de origem e o de destino são iguais.');
    }
    if (d.beneficiary && !toBankCountry(d.beneficiary.country)) {
      throw unprocessable(
        'country_not_supported',
        `O banco não faz transferências para ${d.beneficiary.country}. Países atendidos: ${BANK_COUNTRIES.join(', ')}.`,
        { supported_countries: BANK_COUNTRIES },
      );
    }
  }
  if (req.method === 'pix' && !d.pix_key?.trim()) {
    throw unprocessable('invalid_destination', 'Informe a chave Pix (pix_key).');
  }
  if (req.method === 'bill_payment') {
    const length = digits(d.barcode ?? '').length;
    if (length < 44 || length > 48) {
      throw unprocessable('invalid_barcode', 'Código de barras inválido: são esperados de 44 a 48 dígitos.');
    }
  }
  return { source, currency };
}

interface ResolvedDestination {
  product: Product | null;
  country: BankCountry | null;
  counterparty: Record<string, unknown>;
  decline?: { code: ResponseCode; detail: string };
}

async function lockProducts(tx: Prisma.TransactionClient, ids: string[]): Promise<void> {
  await tx.$executeRaw`SELECT 1 FROM products WHERE product_id IN (${Prisma.join(ids)}) ORDER BY product_id FOR UPDATE`;
}

async function findPixRecipient(tx: Prisma.TransactionClient, key: string, currency: string) {
  const keyDigits = digits(key);
  const [match] = await tx.$queryRaw<{ product_id: string; customer_id: string; name: string; country: string | null }[]>`
    SELECT p.product_id, c.customer_id, concat_ws(' ', c.first_name, c.last_name) AS name, c.country
      FROM customers c
      JOIN products p ON p.customer_id = c.customer_id
     WHERE (lower(c.email) = lower(${key})
            OR c.document_number = ${key}
            OR (length(${keyDigits}) >= 8 AND regexp_replace(c.mobile_phone, '\\D', '', 'g') = ${keyDigits}))
       AND p.product_type IN (${PRODUCT_TYPES.checking}, ${PRODUCT_TYPES.savings})
       AND p.product_status = 'Active'
     ORDER BY (p.currency = ${currency}) DESC, (p.product_type = ${PRODUCT_TYPES.checking}) DESC, p.product_id
     LIMIT 1`;
  return match ?? null;
}

async function resolveDestination(tx: Prisma.TransactionClient, req: PaymentRequest, currency: string): Promise<ResolvedDestination> {
  const d = req.destination;

  if (req.method === 'bill_payment') {
    return {
      product: null,
      country: null,
      counterparty: {
        type: 'bill',
        barcode: digits(d.barcode!),
        biller_name: d.biller_name ?? null,
        due_date: d.due_date ?? null,
        paid_after_due_date: d.due_date != null && d.due_date < today(),
      },
    };
  }

  if (req.method === 'pix') {
    const recipient = await findPixRecipient(tx, d.pix_key!.trim(), currency);
    if (!recipient) {
      return {
        product: null,
        country: null,
        counterparty: { type: 'pix', pix_key: d.pix_key },
        decline: { code: '14', detail: 'Chave Pix não encontrada ou sem conta ativa vinculada.' },
      };
    }
    await lockProducts(tx, [recipient.product_id]);
    return {
      product: await tx.product.findUniqueOrThrow({ where: { product_id: recipient.product_id } }),
      country: toBankCountry(recipient.country),
      counterparty: {
        type: 'pix',
        pix_key: d.pix_key,
        recipient_name: recipient.name,
        recipient_customer_id: recipient.customer_id,
        recipient_product_id: recipient.product_id,
      },
    };
  }

  if (d.beneficiary) {
    const b = d.beneficiary;
    const country = toBankCountry(b.country);
    return {
      product: null,
      country,
      counterparty: {
        type: 'external',
        name: b.name,
        account_number: b.account_number,
        bank_name: b.bank_name ?? null,
        document_number: b.document_number ?? null,
        country,
      },
    };
  }

  let productId = d.to_product_id;
  if (d.to_account_number) {
    const number = d.to_account_number.replace(/[\s.-]/g, '');
    const matches = await tx.product.findMany({
      where: { product_number: number, product_type: { in: [PRODUCT_TYPES.checking, PRODUCT_TYPES.savings] } },
      select: { product_id: true },
      take: 2,
    });
    const counterparty = { type: 'internal', to_account_number: number };
    if (matches.length !== 1) {
      // O dataset tem números de conta repetidos; na dúvida não se credita ninguém.
      const detail = matches.length ? 'Número de conta ambíguo: mais de uma conta com esse número.' : 'Conta de destino não encontrada.';
      return { product: null, country: null, counterparty, decline: { code: '14', detail } };
    }
    productId = matches[0].product_id;
    if (productId === req.sourceProductId) {
      throw unprocessable('invalid_destination', 'O produto de origem e o de destino são iguais.');
    }
  }
  productId = productId!;
  await lockProducts(tx, [productId]);
  const dest = await tx.product.findUnique({ where: { product_id: productId } });
  const counterparty = { type: 'internal', to_product_id: productId, to_account_number: dest?.product_number ?? null };
  if (!dest) {
    return { product: null, country: null, counterparty, decline: { code: '14', detail: 'Conta de destino não encontrada.' } };
  }
  if (![...FUNDS_PRODUCTS, ...DEBT_PRODUCTS].includes(dest.product_type)) {
    throw unprocessable('invalid_destination', `Não é possível transferir para um(a) ${dest.product_type}.`);
  }
  if (dest.product_status !== 'Active') {
    return {
      product: null,
      country: null,
      counterparty,
      decline: { code: '14', detail: `A conta de destino está com status ${dest.product_status}.` },
    };
  }
  const owner = await tx.customer.findUnique({ where: { customer_id: dest.customer_id } });
  return {
    product: dest,
    country: toBankCountry(owner?.country),
    counterparty: {
      ...counterparty,
      to_product_type: dest.product_type,
      recipient_name: owner ? `${owner.first_name} ${owner.last_name}` : null,
      own_product: dest.customer_id === req.customerId,
    },
  };
}

function checkSource(source: Product, debit: Decimal): { code: ResponseCode; detail: string } | null {
  if (source.product_status !== 'Active') {
    return { code: '05', detail: `O produto de origem está com status ${source.product_status}.` };
  }
  const expiration = isoDay(source.expiration_date);
  if (CARD_PRODUCTS.includes(source.product_type) && expiration != null && expiration < today()) {
    return { code: '54', detail: `O cartão venceu em ${expiration}.` };
  }
  const balance = source.current_balance ?? new Decimal(0);
  const isCredit = source.product_type === PRODUCT_TYPES.creditCard;
  const available = isCredit ? (source.credit_limit ?? new Decimal(0)).minus(balance) : balance;
  if (available.lessThan(debit)) {
    return { code: '51', detail: `${isCredit ? 'Limite' : 'Saldo'} disponível (${available.toFixed(2)} ${source.currency}) insuficiente.` };
  }
  return null;
}

async function usdValue(tx: Prisma.TransactionClient, amount: Decimal, currency: string): Promise<Decimal | null> {
  // Mesma convenção do dataset: amount_usd fica vazio quando a moeda já é USD.
  return currency === 'USD' ? null : (await convert(amount, currency, 'USD', undefined, tx)).converted_amount;
}

/** Executa uma operação dentro de uma transação Prisma já aberta. */
export async function executeWithClient(tx: Prisma.TransactionClient, req: PaymentRequest) {
  const { currency } = await validateRequest(tx, req);
  await lockProducts(tx, [req.sourceProductId]);
  const source = await getProduct(req.customerId, req.sourceProductId, tx);
  const customer = await tx.customer.findUniqueOrThrow({ where: { customer_id: req.customerId } });
  const customerCountry = toBankCountry(customer.country);

  const amount = new Decimal(req.amount).toDecimalPlaces(2);
  const sourceConversion = await convert(amount, currency, source.currency, undefined, tx);
  const debit = sourceConversion.converted_amount;

  const destination = await resolveDestination(tx, req, currency);
  const decline = checkSource(source, debit) ?? destination.decline ?? null;

  // Envio para outro país do banco: mostra quanto chega na moeda local do destino.
  const international = destination.country != null && destination.country !== customerCountry;
  const counterparty: Record<string, unknown> = { ...destination.counterparty, international };
  if (international && !destination.product) {
    const localCurrency = COUNTRY_CURRENCY[destination.country!];
    const quote = await convert(amount, currency, localCurrency, undefined, tx);
    counterparty.destination_amount = {
      currency: localCurrency,
      amount: quote.converted_amount,
      rate: quote.rate.exchange_rate,
      rate_date: quote.rate.rate_date,
    };
  }

  const isDebtPayment = destination.product != null && DEBT_PRODUCTS.includes(destination.product.product_type);
  const transactionType = req.method === 'bill_payment' || isDebtPayment ? 'Payment' : 'Transfer';
  const status = decline ? 'Declined' : 'Approved';
  const responseCode: ResponseCode = decline?.code ?? '00';
  const now = new Date();
  const channel = 'App';
  const transactionId = newId('TRX', 20);

  let balanceAfter = source.current_balance ?? new Decimal(0);
  let credited: { transaction_id: string; product_id: string; amount: Decimal; currency: string } | null = null;

  if (!decline) {
    const isCredit = source.product_type === PRODUCT_TYPES.creditCard;
    balanceAfter = isCredit ? balanceAfter.plus(debit) : balanceAfter.minus(debit);
    await tx.product.update({
      where: { product_id: source.product_id },
      data: { current_balance: balanceAfter, last_transaction_date: now },
    });

    const dest = destination.product;
    if (dest) {
      const received = (await convert(amount, currency, dest.currency, undefined, tx)).converted_amount;
      const destIsDebt = DEBT_PRODUCTS.includes(dest.product_type);
      const destBalance = (dest.current_balance ?? new Decimal(0))[destIsDebt ? 'minus' : 'plus'](received);
      await tx.product.update({
        where: { product_id: dest.product_id },
        data: { current_balance: destBalance, last_transaction_date: now },
      });
      const creditId = newId('TRX', 20);
      await tx.transaction.create({
        data: {
          transaction_id: creditId,
          transaction_date: now,
          process_date: now,
          product_id: dest.product_id,
          customer_id: dest.customer_id,
          transaction_type: 'Deposit',
          amount: received,
          currency: dest.currency,
          amount_usd: await usdValue(tx, received, dest.currency),
          channel,
          transaction_country: destination.country,
          transaction_status: 'Approved',
          response_code: '00',
          is_fraud: false,
          origin: 'simulated',
          payment_method: req.method,
          description: `${destIsDebt ? 'Pagamento recebido' : 'Recebido'} de ${source.product_id}`,
          counterparty: { type: 'internal', from_product_id: source.product_id, from_customer_id: req.customerId },
          related_product_id: source.product_id,
          balance_after: destBalance,
        },
      });
      credited = { transaction_id: creditId, product_id: dest.product_id, amount: received, currency: dest.currency };
    }
  }

  await tx.transaction.create({
    data: {
      transaction_id: transactionId,
      transaction_date: now,
      process_date: now,
      product_id: source.product_id,
      customer_id: req.customerId,
      transaction_type: transactionType,
      transaction_category: req.category ?? (req.method === 'bill_payment' ? 'Services' : null),
      amount,
      currency,
      amount_usd: await usdValue(tx, amount, currency),
      channel,
      merchant_name: req.destination.biller_name ?? null,
      transaction_country: customerCountry,
      transaction_city: customer.city,
      transaction_status: status,
      response_code: responseCode,
      is_fraud: false,
      origin: 'simulated',
      payment_method: req.method,
      description: req.description ?? null,
      counterparty: counterparty as Prisma.InputJsonObject,
      related_product_id: destination.product?.product_id ?? null,
      scheduled_payment_id: req.scheduledPaymentId ?? null,
      balance_after: balanceAfter,
    },
  });

  return {
    transaction_id: transactionId as string | null,
    transaction_date: now,
    method: req.method,
    transaction_type: transactionType,
    amount,
    currency,
    source: {
      product_id: source.product_id,
      product_type: source.product_type,
      currency: source.currency,
      debited_amount: decline ? new Decimal(0) : debit,
      balance_after: balanceAfter,
    },
    exchange: currency === source.currency
      ? null
      : { from: currency, to: source.currency, rate: sourceConversion.rate.exchange_rate, rate_date: sourceConversion.rate.rate_date },
    counterparty,
    credited,
    ...explainStatus(status, responseCode),
    decline_detail: decline?.detail ?? null,
  };
}

export type PaymentResult = Awaited<ReturnType<typeof executeWithClient>>;

export function executePayment(req: PaymentRequest): Promise<PaymentResult> {
  return prisma.$transaction((tx) => executeWithClient(tx, req));
}

class PreviewRollback extends Error {
  constructor(public readonly result: PaymentResult) {
    super('preview');
  }
}

/** Simula sem efetivar: mostra conversão, saldo resultante e se haveria recusa. Nada é gravado. */
export async function previewPayment(req: PaymentRequest) {
  const result = await prisma
    .$transaction(async (tx) => {
      throw new PreviewRollback(await executeWithClient(tx, req));
    })
    .catch((err: unknown) => {
      if (err instanceof PreviewRollback) return err.result;
      throw err;
    });
  return { ...result, transaction_id: null, credited: null, preview: true };
}
