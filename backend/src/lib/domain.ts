/** Regras de domínio do Banco LATAM: países, moedas e tipos de produto. */

export const BANK_COUNTRIES = ['México', 'Colombia', 'Argentina'] as const;
export type BankCountry = (typeof BANK_COUNTRIES)[number];

export const COUNTRY_CURRENCY: Record<BankCountry, string> = {
  México: 'MXN',
  Colombia: 'COP',
  Argentina: 'ARS',
};

export const CURRENCIES = ['USD', 'MXN', 'COP', 'ARS'] as const;

const COUNTRY_ALIASES: Record<string, BankCountry> = {
  mexico: 'México',
  mx: 'México',
  colombia: 'Colombia',
  co: 'Colombia',
  argentina: 'Argentina',
  ar: 'Argentina',
};

/** Normaliza o nome de um país do banco; devolve null para países onde o banco não opera. */
export function toBankCountry(value: string | null | undefined): BankCountry | null {
  const key = (value ?? '').normalize('NFD').replace(/\p{Diacritic}/gu, '').trim().toLowerCase();
  return COUNTRY_ALIASES[key] ?? null;
}

export const PRODUCT_TYPES = {
  checking: 'Cuenta Corriente',
  savings: 'Cuenta Ahorro',
  debitCard: 'Tarjeta Débito',
  creditCard: 'Tarjeta Crédito',
  personalLoan: 'Préstamo Personal',
  mortgage: 'Préstamo Hipotecario',
  investment: 'Inversión',
  insurance: 'Seguro',
} as const;

/** Produtos cujo saldo é dinheiro do cliente. */
export const FUNDS_PRODUCTS: string[] = [PRODUCT_TYPES.checking, PRODUCT_TYPES.savings, PRODUCT_TYPES.debitCard];
/** Produtos cujo saldo é dívida do cliente (pagar reduz o saldo). */
export const DEBT_PRODUCTS: string[] = [PRODUCT_TYPES.creditCard, PRODUCT_TYPES.personalLoan, PRODUCT_TYPES.mortgage];
export const LOAN_PRODUCTS: string[] = [PRODUCT_TYPES.personalLoan, PRODUCT_TYPES.mortgage];
export const CARD_PRODUCTS: string[] = [PRODUCT_TYPES.creditCard, PRODUCT_TYPES.debitCard];

export function round2(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/** Mostra só os 4 últimos dígitos do número do produto. */
export function maskNumber(value: string | null): string | null {
  return value ? `•••• ${value.slice(-4)}` : null;
}

/** Date -> "YYYY-MM-DD" (colunas DATE do Postgres). */
export function isoDay(value: Date | null): string | null {
  return value ? value.toISOString().slice(0, 10) : null;
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}
