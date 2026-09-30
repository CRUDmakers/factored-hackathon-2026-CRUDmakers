import { useState, type FormEvent } from 'react';
import { startSession, type Session } from '../api';
import { useI18n, type MessageKey } from '../i18n';
import { TEST_CUSTOMERS } from '../testCustomers';
import { ErrorBox, LangSwitch } from '../ui';

export function Login({ notice, onLogin }: { notice?: MessageKey | null; onLogin?: (s: Session) => void }) {
  const { t, lang } = useI18n();
  const [customerId, setCustomerId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  async function login(id: string) {
    const value = id.trim().toUpperCase();
    if (!value.startsWith('CLI-')) {
      setError(new Error(t('login.invalidId')));
      return;
    }
    setLoading(true);
    setError(null);
    try {
      onLogin?.(await startSession(value));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void login(customerId);
  }

  return (
    <div className="login-page">
      <div className="login-top">
        <LangSwitch />
      </div>
      <div className="login-card">
        <div className="login-brand">
          <img src="/favicon.svg" alt="" width={48} height={48} />
          <div>
            <h1>{t('app.name')}</h1>
            <small>{t('app.tagline')}</small>
          </div>
        </div>

        <div className="demo-banner">
          <strong>⚠ {t('login.demoBadge')}</strong>
          <p>{t('login.demoText')}</p>
        </div>

        {notice && (
          <div className="alert alert-warn" role="alert">
            {t(notice)}
          </div>
        )}

        <h2>{t('login.title')}</h2>
        <form onSubmit={submit} className="stack">
          <label className="field">
            <span>{t('login.customerId')}</span>
            <input
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              placeholder={t('login.placeholder')}
              autoComplete="off"
              spellCheck={false}
              required
            />
          </label>
          <button className="btn btn-primary btn-block" disabled={loading}>
            {loading ? t('common.loading') : t('login.submit')}
          </button>
        </form>

        {error != null && <ErrorBox error={error} />}

        <h3 className="shortcuts-title">{t('login.shortcuts')}</h3>
        <ul className="shortcuts">
          {TEST_CUSTOMERS.map((c) => (
            <li key={c.id}>
              <button type="button" disabled={loading} onClick={() => (setCustomerId(c.id), void login(c.id))}>
                <span className="sc-country">{c.country}</span>
                <span className="sc-main">
                  <strong>{c.name}</strong>
                  <code>{c.id}</code>
                </span>
                <small>{c.note[lang]}</small>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
