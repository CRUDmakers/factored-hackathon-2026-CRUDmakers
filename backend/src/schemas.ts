import { Type } from '@fastify/type-provider-typebox';
import { BANK_COUNTRIES, CURRENCIES } from './lib/domain.js';

export const CustomerParams = Type.Object({
  customerId: Type.String({ pattern: '^CLI-', description: 'ID do cliente, ex.: CLI-G4X2AMVD62NR', examples: ['CLI-G4X2AMVD62NR'] }),
});

export const ProductParams = Type.Object({
  customerId: CustomerParams.properties.customerId,
  productId: Type.String({ pattern: '^PRD-', description: 'ID do produto' }),
});

export const TransactionParams = Type.Object({
  customerId: CustomerParams.properties.customerId,
  transactionId: Type.String({ pattern: '^TRX-', description: 'ID da transação' }),
});

export const ScheduleParams = Type.Object({
  customerId: CustomerParams.properties.customerId,
  scheduledPaymentId: Type.String({ pattern: '^SCH-', description: 'ID do agendamento' }),
});

const Day = (description: string) => Type.String({ format: 'date', description });
const Currency = Type.Enum([...CURRENCIES], { description: 'Moeda (USD, MXN, COP, ARS)' });

export const PeriodQuery = Type.Object({
  from: Type.Optional(Day('Data inicial (YYYY-MM-DD). Padrão: N dias antes de `to`.')),
  to: Type.Optional(Day('Data final (YYYY-MM-DD). Padrão: data da última transação do cliente.')),
});

export const ProductsQuery = Type.Object({
  type: Type.Optional(Type.String({ description: 'Tipo, ex.: Tarjeta Crédito, Cuenta Corriente' })),
  status: Type.Optional(Type.String({ description: 'Active, Closed, Blocked ou Suspended' })),
});

export const TransactionsQuery = Type.Object({
  from: Type.Optional(Day('Data inicial')),
  to: Type.Optional(Day('Data final')),
  type: Type.Optional(Type.Enum(['Purchase', 'Withdrawal', 'Transfer', 'Payment', 'Deposit', 'Adjustment'])),
  status: Type.Optional(Type.Enum(['Approved', 'Declined', 'Pending', 'Reversed'])),
  category: Type.Optional(Type.String({ description: 'Food, Services, Transport, Entertainment, Health, Other, Withdrawals, Transfers, Uncategorized' })),
  channel: Type.Optional(Type.Enum(['POS', 'ATM', 'Web', 'App', 'Branch', 'Transfer'])),
  product_id: Type.Optional(Type.String()),
  origin: Type.Optional(Type.Enum(['historical', 'simulated'])),
  // Com default, o ajv preenche o valor antes da validação: o campo nunca chega vazio.
  limit: Type.Integer({ minimum: 1, maximum: 500, default: 50 }),
  offset: Type.Integer({ minimum: 0, default: 0 }),
});

export const AdjustmentsQuery = Type.Object({
  product_id: Type.Optional(Type.String()),
  loans_only: Type.Boolean({ default: true, description: 'false inclui investimentos e seguros' }),
  limit: Type.Integer({ minimum: 1, maximum: 500, default: 50 }),
});

export const DryRunQuery = Type.Object({
  dry_run: Type.Optional(Type.Boolean({ default: false, description: 'true simula sem gravar nem mover saldo' })),
});

const Common = {
  source_product_id: Type.String({ description: 'Produto de onde sai o dinheiro (conta, cartão de débito ou, para boletos, cartão de crédito)' }),
  amount: Type.Number({ exclusiveMinimum: 0, description: 'Valor da operação' }),
  currency: Type.Optional(Currency),
  description: Type.Optional(Type.String({ maxLength: 200 })),
};

export const Beneficiary = Type.Object({
  name: Type.String({ minLength: 1 }),
  account_number: Type.String({ minLength: 1 }),
  bank_name: Type.Optional(Type.String()),
  country: Type.String({ description: `País do beneficiário. O banco opera em: ${BANK_COUNTRIES.join(', ')}` }),
  document_number: Type.Optional(Type.String()),
});

const TransferDestination = Type.Object({
  to_product_id: Type.Optional(Type.String({ description: 'Conta/cartão/empréstimo de destino no próprio banco' })),
  beneficiary: Type.Optional(Beneficiary),
});
const PixDestination = Type.Object({
  pix_key: Type.String({ minLength: 1, description: 'E-mail, celular ou documento do destinatário' }),
});
const BillDestination = Type.Object({
  barcode: Type.String({ description: 'Código de barras / linha digitável (44 a 48 dígitos)' }),
  biller_name: Type.Optional(Type.String()),
  due_date: Type.Optional(Day('Vencimento')),
});

export const TransferBody = Type.Object({ ...Common, ...TransferDestination.properties });
export const PixBody = Type.Object({ ...Common, ...PixDestination.properties });
export const BillPaymentBody = Type.Object({
  ...Common,
  ...BillDestination.properties,
  category: Type.Optional(Type.String({ description: 'Categoria do gasto. Padrão: Services' })),
});

export const CreateScheduleBody = Type.Object({
  ...Common,
  method: Type.Enum(['transfer', 'pix', 'bill_payment']),
  destination: Type.Object({
    ...TransferDestination.properties,
    pix_key: Type.Optional(PixDestination.properties.pix_key),
    barcode: Type.Optional(BillDestination.properties.barcode),
    biller_name: BillDestination.properties.biller_name,
    due_date: BillDestination.properties.due_date,
  }),
  frequency: Type.Enum(['once', 'daily', 'weekly', 'monthly']),
  start_at: Type.Optional(Type.String({ format: 'date-time', description: 'Primeira execução. Padrão: agora' })),
  end_date: Type.Optional(Day('Último dia em que pode executar')),
  max_executions: Type.Optional(Type.Integer({ minimum: 1 })),
});

export const UpdateScheduleBody = Type.Object({
  status: Type.Optional(Type.Enum(['active', 'paused'])),
  amount: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  next_run_at: Type.Optional(Type.String({ format: 'date-time' })),
  end_date: Type.Optional(Day('Último dia em que pode executar')),
  description: Type.Optional(Type.String({ maxLength: 200 })),
});

export const ScheduleListQuery = Type.Object({
  status: Type.Optional(Type.Enum(['active', 'paused', 'cancelled', 'completed', 'failed'])),
});

export const RateQuery = Type.Object({
  from: Currency,
  to: Currency,
  date: Type.Optional(Day('Cotação mais recente até esta data. Padrão: a última disponível')),
});

export const ConvertQuery = Type.Object({
  ...RateQuery.properties,
  amount: Type.Number({ exclusiveMinimum: 0 }),
});

export const RateHistoryQuery = Type.Object({
  from: Currency,
  to: Currency,
  start: Day('Data inicial'),
  end: Day('Data final'),
});

export const ErrorResponse = Type.Object({
  error: Type.String(),
  message: Type.String(),
  details: Type.Optional(Type.Unknown()),
});
