import { useState, type FormEvent } from 'react';
import { api, type Conversion } from '../api';
import { useI18n } from '../i18n';
import { Card, day, ErrorBox, money, num } from '../ui';
import { CURRENCIES } from './PaymentForm';

export function Exchange() {
  const { t, lang } = useI18n();
  const [from, setFrom] = useState('USD');
  const [to, setTo] = useState('MXN');
  const [amount, setAmount] = useState('100');
  const [result, setResult] = useState<Conversion | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.convert({ from, to, amount: Number(amount) }));
    } catch (err) {
      setResult(null);
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pay-layout">
      <Card title={t('fx.title')}>
        <form onSubmit={submit} className="stack">
          <label className="field">
            <span>{t('common.amount')}</span>
            <input type="number" inputMode="decimal" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
          </label>
          <div className="row fx-row">
            <label className="field grow">
              <span>{t('fx.from')}</span>
              <select value={from} onChange={(e) => setFrom(e.target.value)}>
                {CURRENCIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn-ghost swap"
              aria-label={t('fx.swap')}
              title={t('fx.swap')}
              onClick={() => {
                setFrom(to);
                setTo(from);
              }}
            >
              ⇄
            </button>
            <label className="field grow">
              <span>{t('fx.to')}</span>
              <select value={to} onChange={(e) => setTo(e.target.value)}>
                {CURRENCIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
          </div>
          <button className="btn btn-primary btn-block" disabled={busy}>
            {busy ? t('common.loading') : t('fx.convert')}
          </button>
        </form>

        {error != null && <ErrorBox error={error} />}
        {result && (
          <div className="fx-result">
            <small>
              {money(result.amount, result.rate.source_currency, lang)} =
            </small>
            <strong>{money(result.converted_amount, result.rate.target_currency, lang)}</strong>
            <dl className="kv">
              <dt>{t('fx.rate')}</dt>
              <dd>
                1 {result.rate.source_currency} = {num(result.rate.exchange_rate, lang, 6)} {result.rate.target_currency}
              </dd>
              {result.rate.buy_rate != null && (
                <>
                  <dt>{t('fx.buy')}</dt>
                  <dd>{num(result.rate.buy_rate, lang, 6)}</dd>
                </>
              )}
              {result.rate.sell_rate != null && (
                <>
                  <dt>{t('fx.sell')}</dt>
                  <dd>{num(result.rate.sell_rate, lang, 6)}</dd>
                </>
              )}
              <dt>{t('fx.date')}</dt>
              <dd>
                {day(result.rate.rate_date, lang)}
                {result.rate.source ? ` · ${result.rate.source}` : ''}
              </dd>
            </dl>
          </div>
        )}
        <p className="muted small">{t('fx.note')}</p>
      </Card>
    </div>
  );
}
