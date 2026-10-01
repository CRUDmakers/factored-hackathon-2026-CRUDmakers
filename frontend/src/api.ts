/**
 * Único módulo que conversa com o Backend 1. Se o contrato da autenticação mudar,
 * ajuste só aqui (startSession / endSession / tratamento de 401 e 403).
 */

export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:3000').replace(/\/$/, '');
/** Backend 2 (assistente de IA). Usa o mesmo token de sessão; contrato em ai-backend/CHAT_API.md. */
export const AI_URL = (import.meta.env.VITE_AI_URL ?? 'http://localhost:8000').replace(/\/$/, '');
/** Chave do provedor de identidade de TESTE. Exposta no bundle: aceitável só para a demo. */
const SERVICE_KEY = import.meta.env.VITE_SERVICE_KEY ?? 'dev-service-key';

// ---------- erros ----------

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
  get isForbidden() {
    return this.status === 403;
  }
}

// ---------- sessão ----------

export interface Session {
  token: string;
  customerId: string;
  expiresAt: string;
}

const STORAGE_KEY = 'banco-latam-session';

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function saveSession(session: Session | null) {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* sessionStorage indisponível: fica só em memória */
  }
}

let current: Session | null = loadSession();
/** Chamado quando a API diz que a sessão não vale mais (401). O App volta ao login. */
let onSessionLost: (reason: 'expired' | 'invalid') => void = () => {};

export function setSessionLostHandler(fn: typeof onSessionLost) {
  onSessionLost = fn;
}

export function getSession() {
  return current;
}

// ---------- HTTP ----------

type Query = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, query?: Query, base = API_URL) {
  const url = new URL(base + path);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  }
  return url.toString();
}

async function request<T>(
  method: string,
  path: string,
  opts: { query?: Query; body?: unknown; headers?: Record<string, string>; auth?: boolean; base?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...opts.headers };
  if (opts.body !== undefined) headers['content-type'] = 'application/json';
  if (opts.auth !== false && current) headers.authorization = `Bearer ${current.token}`;

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query, opts.base), {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'network_error', `Não foi possível conectar à API (${opts.base ?? API_URL}).`);
  }

  if (res.status === 204) return undefined as T;
  const data = (await res.json().catch(() => null)) as { error?: string; message?: string; details?: unknown } | null;
  if (!res.ok) {
    const err = new ApiError(res.status, data?.error ?? 'http_error', data?.message ?? `HTTP ${res.status}`, data?.details);
    // 401 numa rota com sessão: token expirado, encerrado ou inválido -> volta ao login.
    if (res.status === 401 && opts.auth !== false && current) {
      clearSession();
      onSessionLost(err.code === 'session_expired' ? 'expired' : 'invalid');
    }
    throw err;
  }
  return data as T;
}

/** O relógio local passou de expires_at: encerra antes mesmo da próxima chamada à API. */
export function expireLocally() {
  if (!current) return;
  clearSession();
  onSessionLost('expired');
}

function clearSession() {
  current = null;
  saveSession(null);
}

const customerPath = (suffix = '') => `/api/customers/${encodeURIComponent(current?.customerId ?? '')}${suffix}`;

// ---------- autenticação (serviço de identidade de TESTE) ----------

interface TestSessionResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  expires_at: string;
  session_id: string;
  customer_id: string;
}

/** POST /auth/test-sessions com a chave de serviço: emite um JWT curto para o cliente. */
export async function startSession(customerId: string): Promise<Session> {
  const res = await request<TestSessionResponse>('POST', '/auth/test-sessions', {
    body: { customer_id: customerId },
    headers: { 'x-service-key': SERVICE_KEY },
    auth: false,
  });
  current = { token: res.access_token, customerId: res.customer_id, expiresAt: res.expires_at };
  saveSession(current);
  return current;
}

/** Logout: DELETE /auth/sessions/current (erros ignorados; a sessão local é apagada de qualquer jeito). */
export async function endSession() {
  const token = current?.token;
  clearSession();
  if (!token) return;
  await fetch(buildUrl('/auth/sessions/current'), { method: 'DELETE', headers: { authorization: `Bearer ${token}` } }).catch(
    () => undefined,
  );
}

// ---------- tipos das respostas ----------

export interface Customer {
  customer_id: string;
  first_name: string | null;
  last_name: string | null;
  country: string | null;
  city: string | null;
  segment: string | null;
  email: string | null;
}

export interface Account {
  product_id: string;
  product_type: string;
  product_number: string | null;
  currency: string;
  status: string;
  balance: number;
}

export interface CreditCard {
  product_id: string;
  product_number: string | null;
  currency: string;
  status: string;
  invoice_amount: number;
  credit_limit: number;
  available_credit: number;
  utilization_pct: number | null;
  interest_rate: number | null;
  expiration_date: string | null;
  days_past_due: number | null;
}

export interface Loan {
  product_id: string;
  product_type: string;
  currency: string;
  status: string;
  outstanding_balance: number;
  interest_rate: number | null;
  expiration_date: string | null;
  days_past_due: number | null;
}

export interface Balances {
  customer_id: string;
  accounts: Account[];
  credit_cards: CreditCard[];
  loans: Loan[];
  investments: { product_id: string; product_type: string; currency: string; balance?: number }[];
  totals_by_currency: { currency: string; available_funds: number; investments: number; debt: number; net: number }[];
  net_worth_usd: number;
}

export interface Product {
  product_id: string;
  product_type: string;
  product_number: string | null;
  currency: string;
  status: string;
  current_balance: number | null;
  credit_limit: number | null;
  available_credit: number | null;
  is_expired: boolean;
  expiration_date: string | null;
}

export interface TransactionItem {
  transaction_id: string;
  transaction_date: string;
  product_id: string | null;
  product_type: string | null;
  transaction_type: string | null;
  category: string;
  direction: 'in' | 'out' | 'adjustment';
  amount: number;
  currency: string;
  amount_usd: number | null;
  channel: string | null;
  merchant_name: string | null;
  transaction_city: string | null;
  transaction_country: string | null;
  transaction_status: string | null;
  response_code: string | null;
  origin: string;
  payment_method: string | null;
  description: string | null;
  status_reason: string | null;
}

export interface TransactionPage {
  total: number;
  limit: number;
  offset: number;
  items: TransactionItem[];
}

export interface StatusInfo {
  status: string | null;
  status_description: string;
  completed: boolean;
  response_code: string | null;
  reason_code: string | null;
  reason: string | null;
}

export interface TransactionDetail {
  transaction_id: string;
  transaction_date: string;
  process_date: string | null;
  product_id: string | null;
  product_type: string | null;
  transaction_type: string | null;
  transaction_category: string | null;
  amount: number;
  currency: string;
  amount_usd: number | null;
  channel: string | null;
  merchant_name: string | null;
  merchant_category: string | null;
  origin: string;
  payment_method: string | null;
  description: string | null;
  counterparty: Record<string, unknown> | null;
  balance_after: number | null;
  flagged_as_fraud: boolean;
  status: StatusInfo;
  location: {
    summary: string;
    city: string | null;
    country: string | null;
    coordinates: { latitude: number; longitude: number } | null;
    branch: { branch_name?: string | null; address?: string | null; city?: string | null } | null;
  };
}

export interface PaymentResult {
  transaction_id: string | null;
  transaction_date: string;
  method: PaymentMethod;
  amount: number;
  currency: string;
  source: { product_id: string; product_type: string; currency: string; debited_amount: number; balance_after: number };
  exchange: { from: string; to: string; rate: number; rate_date: string } | null;
  counterparty: Record<string, unknown> & {
    destination_amount?: { currency: string; amount: number; rate: number; rate_date: string };
    name?: string;
  };
  credited: Record<string, unknown> | null;
  status: string;
  status_description: string;
  completed: boolean;
  response_code: string | null;
  reason_code: string | null;
  reason: string | null;
  decline_detail: string | null;
  preview?: boolean;
}

export type PaymentMethod = 'transfer' | 'pix' | 'bill_payment';

export interface PaymentBody {
  source_product_id: string;
  amount: number;
  currency?: string;
  description?: string;
  // transferência
  to_account_number?: string;
  to_product_id?: string;
  beneficiary?: { name: string; account_number: string; bank_name?: string; country: string; document_number?: string };
  // pix
  pix_key?: string;
  // boleto
  barcode?: string;
  biller_name?: string;
  due_date?: string;
}

export interface Schedule {
  scheduled_payment_id: string;
  product_id: string;
  payment_method: PaymentMethod;
  amount: number | string;
  currency: string;
  destination: Record<string, unknown>;
  description: string | null;
  frequency: 'once' | 'daily' | 'weekly' | 'monthly';
  next_run_at: string | null;
  end_date: string | null;
  max_executions: number | null;
  executions_count: number;
  status: 'active' | 'paused' | 'cancelled' | 'completed' | 'failed';
  last_run_at: string | null;
  last_result: string | null;
  created_at: string;
}

export interface CreateScheduleBody {
  source_product_id: string;
  amount: number;
  currency?: string;
  description?: string;
  method: PaymentMethod;
  destination: Omit<PaymentBody, 'source_product_id' | 'amount' | 'currency' | 'description'>;
  frequency: Schedule['frequency'];
  start_at?: string;
  end_date?: string;
  max_executions?: number;
}

export interface Spending {
  period: { from: string; to: string };
  currency: string;
  total_spent_usd: number;
  monthly_average_usd: number;
  by_category: { category: string; count: number; total_usd: number; share_pct: number; monthly_average_usd: number }[];
  by_month: { month: string; total_usd: number; categories: Record<string, number> }[];
}

export interface Conversion {
  amount: number;
  converted_amount: number;
  rate: {
    source_currency: string;
    target_currency: string;
    rate_date: string;
    exchange_rate: number;
    buy_rate: number | null;
    sell_rate: number | null;
    source: string | null;
  };
}

export interface ChatRequest {
  conversation_id?: string;
  message?: string;
  confirmation?: { action_id: string; decision: 'approve' | 'reject' };
}

/** Planilha gerada pelo assistente; baixe com `downloadChatFile`. */
export interface ChatFile {
  file_id: string;
  filename: string;
  format: 'xlsx' | 'csv';
  media_type: string;
  size_bytes: number;
  rows: number;
  download_url: string;
  expires_at: string;
}

export interface ChatResponse {
  conversation_id: string;
  turn_id: string;
  status: 'answered' | 'awaiting_confirmation' | 'handed_off' | 'refused';
  message: string;
  language: 'es' | 'pt';
  pending_action: { action_id: string; summary: string; preview: PaymentResult; expires_at: string } | null;
  handoff: { handoff_id: string } | null;
  files?: ChatFile[];
  trace_id: string;
}

// ---------- endpoints ----------

const PAYMENT_PATH: Record<PaymentMethod, string> = {
  transfer: '/transfers',
  pix: '/pix',
  bill_payment: '/bill-payments',
};

export const api = {
  customer: () => request<Customer>('GET', customerPath()),
  balances: () => request<Balances>('GET', customerPath('/balances')),
  products: () => request<Product[]>('GET', customerPath('/products')),
  transactions: (query: Query) => request<TransactionPage>('GET', customerPath('/transactions'), { query }),
  transaction: (id: string) => request<TransactionDetail>('GET', customerPath(`/transactions/${encodeURIComponent(id)}`)),
  pay: (method: PaymentMethod, body: PaymentBody, dryRun: boolean) =>
    request<PaymentResult>('POST', customerPath(PAYMENT_PATH[method]), { body, query: { dry_run: dryRun || undefined } }),
  schedules: (status?: string) => request<Schedule[]>('GET', customerPath('/scheduled-payments'), { query: { status } }),
  createSchedule: (body: CreateScheduleBody) => request<Schedule>('POST', customerPath('/scheduled-payments'), { body }),
  updateSchedule: (id: string, patch: { status: 'active' | 'paused' }) =>
    request<Schedule>('PATCH', customerPath(`/scheduled-payments/${encodeURIComponent(id)}`), { body: patch }),
  cancelSchedule: (id: string) => request<Schedule>('DELETE', customerPath(`/scheduled-payments/${encodeURIComponent(id)}`)),
  spending: (query: Query) => request<Spending>('GET', customerPath('/reports/spending'), { query }),
  convert: (query: { from: string; to: string; amount: number }) =>
    request<Conversion>('GET', '/api/exchange-rates/convert', { query, auth: false }),
  chat: (body: ChatRequest) => request<ChatResponse>('POST', '/v1/chat', { body, base: AI_URL }),
};

/** Baixa um arquivo gerado pelo assistente (precisa do token, então não dá para usar um <a href>). */
export async function downloadChatFile(file: ChatFile): Promise<void> {
  const headers: Record<string, string> = current ? { authorization: `Bearer ${current.token}` } : {};
  let res: Response;
  try {
    res = await fetch(AI_URL + file.download_url, { headers });
  } catch {
    throw new ApiError(0, 'network_error', `Não foi possível conectar à API (${AI_URL}).`);
  }
  if (!res.ok) {
    const data = (await res.json().catch(() => null)) as { error?: string; message?: string } | null;
    const err = new ApiError(res.status, data?.error ?? 'http_error', data?.message ?? `HTTP ${res.status}`);
    // 401: sessão expirada ou encerrada -> volta ao login, como em `request`.
    if (res.status === 401 && current) {
      clearSession();
      onSessionLost('expired');
    }
    throw err;
  }
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = file.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
