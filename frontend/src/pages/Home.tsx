import { api } from '../api';
import { useI18n } from '../i18n';
import { Card, day, ErrorBox, Loading, money, num, useAsync } from '../ui';

export function Home() {
  const { t, tv, lang } = useI18n();
  const { data, error, loading, reload } = useAsync(() => api.balances(), []);

  const today = new Date().toISOString().slice(0, 10);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div className="stack-lg">
      <div className="hero">
        <span>{t('home.netWorth')}</span>
        <strong className={data.net_worth_usd < 0 ? 'neg' : ''}>{money(data.net_worth_usd, 'USD', lang)}</strong>
        <div className="hero-totals">
          {data.totals_by_currency.map((c) => (
            <div key={c.currency}>
              <small>{c.currency}</small>
              <span>
                {t('home.funds')}: {money(c.available_funds, c.currency, lang)}
              </span>
              <span>
                {t('home.debt')}: {money(c.debt, c.currency, lang)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <Card title={t('home.accounts')}>
        {data.accounts.length === 0 && <p className="muted">{t('home.noItems')}</p>}
        <ul className="product-list">
          {data.accounts.map((a) => (
            <li key={a.product_id}>
              <div>
                <strong>{tv('product', a.product_type)}</strong>
                <small>
                  {a.product_number} · {a.status !== 'Active' ? <em className="tag-warn">{a.status}</em> : a.currency}
                </small>
              </div>
              <div className="amount">
                <small>{t('home.balance')}</small>
                <strong>{money(a.balance, a.currency, lang)}</strong>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <Card title={t('home.cards')}>
        {data.credit_cards.length === 0 && <p className="muted">{t('home.noItems')}</p>}
        <div className="grid-cards">
          {data.credit_cards.map((c) => {
            const pct = c.utilization_pct ?? (c.credit_limit > 0 ? (c.invoice_amount / c.credit_limit) * 100 : 100);
            return (
              <article key={c.product_id} className="credit-card">
                <header>
                  <span>{tv('product', 'Tarjeta Crédito')}</span>
                  <code>{c.product_number}</code>
                </header>
                <dl>
                  <dt>{t('home.invoice')}</dt>
                  <dd>{money(c.invoice_amount, c.currency, lang)}</dd>
                  <dt>{t('home.limit')}</dt>
                  <dd>{money(c.credit_limit, c.currency, lang)}</dd>
                  <dt>{t('home.available')}</dt>
                  <dd className={c.available_credit < 0 ? 'neg' : 'pos'}>{money(c.available_credit, c.currency, lang)}</dd>
                </dl>
                <div className="meter" aria-label={t('home.usage')} title={`${t('home.usage')}: ${num(pct, lang, 1)}%`}>
                  <span style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} className={pct > 80 ? 'hot' : ''} />
                </div>
                <footer>
                  <span>
                    {t('home.rate')}: {c.interest_rate != null ? `${num(c.interest_rate, lang)}%` : '—'}
                  </span>
                  <span>
                    {t('home.expires')}: {day(c.expiration_date, lang)}
                  </span>
                  {!!c.days_past_due && (
                    <em className="tag-warn">
                      {c.days_past_due} {t('home.pastDue')}
                    </em>
                  )}
                  {c.expiration_date && c.expiration_date < today && <em className="tag-warn">{t('home.expired')}</em>}
                  {c.status !== 'Active' && <em className="tag-warn">{c.status}</em>}
                </footer>
              </article>
            );
          })}
        </div>
      </Card>

      <Card title={t('home.loans')}>
        {data.loans.length === 0 && <p className="muted">{t('home.noItems')}</p>}
        <ul className="product-list">
          {data.loans.map((l) => (
            <li key={l.product_id}>
              <div>
                <strong>{tv('product', l.product_type)}</strong>
                <small>
                  {t('home.rate')}: {l.interest_rate != null ? `${num(l.interest_rate, lang)}%` : '—'} · {t('home.expires')}:{' '}
                  {day(l.expiration_date, lang)}
                  {!!l.days_past_due && (
                    <em className="tag-warn">
                      {' '}
                      {l.days_past_due} {t('home.pastDue')}
                    </em>
                  )}
                </small>
              </div>
              <div className="amount">
                <small>{t('home.outstanding')}</small>
                <strong>{money(l.outstanding_balance, l.currency, lang)}</strong>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
