import { useState, type FormEvent } from 'react';
import { api } from '../api';
import { useI18n } from '../i18n';
import { Card, day, ErrorBox, Loading, money, num, useAsync } from '../ui';

const COLORS = ['#0b3d62', '#1f7a8c', '#f2b705', '#d9534f', '#6c8ea4', '#7e57c2', '#43a047', '#ef6c00', '#8d6e63'];

export function Reports() {
  const { t, tv, lang } = useI18n();
  const [draft, setDraft] = useState({ from: '', to: '' });
  const [period, setPeriod] = useState({ from: '', to: '' });
  const { data, error, loading, reload } = useAsync(() => api.spending(period), [period]);

  function apply(e: FormEvent) {
    e.preventDefault();
    setPeriod(draft);
  }

  const max = data ? Math.max(1, ...data.by_category.map((c) => c.total_usd)) : 1;
  const maxMonth = data ? Math.max(1, ...data.by_month.map((m) => m.total_usd)) : 1;

  return (
    <div className="stack-lg">
      <Card title={t('rep.title')}>
        <form className="filters" onSubmit={apply}>
          <label className="field">
            <span>{t('common.from')}</span>
            <input type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
          </label>
          <label className="field">
            <span>{t('common.to')}</span>
            <input type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </label>
          <div className="filter-actions">
            <button className="btn btn-primary">{t('common.apply')}</button>
          </div>
          <div className="filter-actions">
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => {
                const p = { from: '2026-03-19', to: '2026-06-17' };
                setDraft(p);
                setPeriod(p);
              }}
            >
              {t('rep.historical')}
            </button>
          </div>
        </form>
        <p className="muted small">{t('rep.note')}</p>

        {error != null ? (
          <ErrorBox error={error} onRetry={reload} />
        ) : !data || loading ? (
          <Loading />
        ) : (
          <div className="stack-lg">
            <div className="stats">
              <div>
                <small>{t('rep.period')}</small>
                <strong>
                  {day(data.period.from, lang)} – {day(data.period.to, lang)}
                </strong>
              </div>
              <div>
                <small>{t('rep.total')}</small>
                <strong>{money(data.total_spent_usd, 'USD', lang)}</strong>
              </div>
              <div>
                <small>{t('rep.avg')}</small>
                <strong>{money(data.monthly_average_usd, 'USD', lang)}</strong>
              </div>
            </div>

            {data.by_category.length === 0 ? (
              <p className="muted">{t('common.empty')}</p>
            ) : (
              <ul className="bars">
                {data.by_category.map((c, i) => (
                  <li key={c.category}>
                    <span className="bar-label">
                      {tv('cat', c.category)} <small className="muted">({c.count})</small>
                    </span>
                    <span className="bar-track">
                      <span className="bar-fill" style={{ width: `${(c.total_usd / max) * 100}%`, background: COLORS[i % COLORS.length] }} />
                    </span>
                    <span className="bar-value">
                      {money(c.total_usd, 'USD', lang)} <small className="muted">{num(c.share_pct, lang, 1)}%</small>
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {data.by_month.length > 0 && (
              <>
                <h3>{t('rep.byMonth')}</h3>
                <MonthChart months={data.by_month} max={maxMonth} lang={lang} />
              </>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function MonthChart({ months, max, lang }: { months: { month: string; total_usd: number }[]; max: number; lang: 'es' | 'pt' }) {
  const w = 60;
  const h = 160;
  const width = months.length * w;
  return (
    <div className="month-chart">
      <svg viewBox={`0 0 ${width} ${h + 36}`} width="100%" height={h + 36} role="img" preserveAspectRatio="xMinYMid meet">
        {months.map((m, i) => {
          const bh = Math.max(2, (m.total_usd / max) * h);
          return (
            <g key={m.month} transform={`translate(${i * w},0)`}>
              <title>
                {m.month}: {money(m.total_usd, 'USD', lang)}
              </title>
              <rect x={12} y={h - bh + 14} width={w - 24} height={bh} rx={4} fill="var(--brand-2)" />
              <text x={w / 2} y={h - bh + 10} textAnchor="middle" fontSize="10" fill="var(--muted)">
                {num(m.total_usd, lang, 0)}
              </text>
              <text x={w / 2} y={h + 30} textAnchor="middle" fontSize="11" fill="var(--text)">
                {m.month}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
