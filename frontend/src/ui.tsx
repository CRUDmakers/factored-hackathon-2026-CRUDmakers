import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ApiError } from './api';
import { useI18n, type Lang } from './i18n';

// ---------- formatação ----------

const LOCALE: Record<Lang, string> = { es: 'es-MX', pt: 'pt-BR' };

export function money(value: number | string | null | undefined, currency: string, lang: Lang) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  try {
    return new Intl.NumberFormat(LOCALE[lang], { style: 'currency', currency, currencyDisplay: 'code' }).format(n);
  } catch {
    return `${currency} ${n.toFixed(2)}`;
  }
}

export function num(value: number | null | undefined, lang: Lang, digits = 2) {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat(LOCALE[lang], { maximumFractionDigits: digits }).format(value);
}

export function dateTime(value: string | null | undefined, lang: Lang) {
  if (!value) return '—';
  return new Intl.DateTimeFormat(LOCALE[lang], { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
}

/** Datas "YYYY-MM-DD" sem fuso (evita voltar um dia em UTC-x). */
export function day(value: string | null | undefined, lang: Lang) {
  if (!value) return '—';
  const [y, m, d] = value.slice(0, 10).split('-').map(Number);
  return new Intl.DateTimeFormat(LOCALE[lang], { dateStyle: 'short' }).format(new Date(y, m - 1, d));
}

// ---------- estado assíncrono ----------

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: unknown; loading: boolean }>({ loading: true });
  const run = useCallback(fn, deps);
  const reload = useCallback(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    run().then(
      (data) => alive && setState({ data, loading: false }),
      (error) => alive && setState({ error, loading: false }),
    );
    return () => {
      alive = false;
    };
  }, [run]);
  useEffect(reload, [reload]);
  return { ...state, reload };
}

// ---------- componentes ----------

export function Loading() {
  const { t } = useI18n();
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden /> {t('common.loading')}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  const forbidden = error instanceof ApiError && error.isForbidden && error.code === 'forbidden';
  const message = forbidden
    ? t('common.forbidden')
    : error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : String(error);
  return (
    <div className={`alert ${forbidden ? 'alert-forbidden' : 'alert-error'}`} role="alert">
      <strong>{forbidden ? '403' : t('common.error')}:</strong> {message}
      {error instanceof ApiError && !forbidden && error.code && <code className="err-code">{error.code}</code>}
      {onRetry && (
        <button type="button" className="btn btn-small btn-ghost" onClick={onRetry}>
          {t('common.retry')}
        </button>
      )}
    </div>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const { tv } = useI18n();
  const cls = status === 'Approved' ? 'ok' : status === 'Declined' ? 'bad' : 'warn';
  return <span className={`badge badge-${cls}`}>{tv('status', status)}</span>;
}

export function Card({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="lang-switch" role="group" aria-label={t('lang.label')}>
      {(['es', 'pt'] as const).map((l) => (
        <button key={l} type="button" className={l === lang ? 'active' : ''} aria-pressed={l === lang} onClick={() => setLang(l)}>
          {l === 'es' ? 'ES' : 'PT'}
        </button>
      ))}
    </div>
  );
}

// ---------- textos vindos da API ----------
// A API responde em pt-BR, mas com códigos neutros. Quando há código conhecido, o texto sai no idioma da tela.

const ISO_REASON: Record<string, string> = { '05': 'do_not_honor', '14': 'invalid_account', '51': 'insufficient_funds', '54': 'expired_card' };

export function useApiText() {
  const { tv } = useI18n();
  return {
    reason(reasonCode: string | null | undefined, fallback: string | null | undefined, isoCode?: string | null) {
      const code = reasonCode ?? (isoCode ? ISO_REASON[isoCode] : undefined);
      if (code) {
        const text = tv('reason', code);
        if (text !== code) return text;
      }
      return fallback ?? null;
    },
    status(status: string | null | undefined, fallback: string) {
      const text = tv('statusText', status);
      return text === status || text === '—' ? fallback : text;
    },
  };
}
