import { useEffect, useMemo, useState } from 'react';
import { api, endSession, expireLocally, getSession, setSessionLostHandler, type Customer, type Session } from './api';
import { I18nContext, initialLang, makeI18n, persistLang, useI18n, type Lang, type MessageKey } from './i18n';
import { Assistant } from './pages/Assistant';
import { Exchange } from './pages/Exchange';
import { Home } from './pages/Home';
import { Login } from './pages/Login';
import { Pay } from './pages/Pay';
import { Reports } from './pages/Reports';
import { Schedules } from './pages/Schedules';
import { Statement } from './pages/Statement';
import { LangSwitch } from './ui';

const ROUTES = ['home', 'statement', 'pay', 'schedules', 'reports', 'fx'] as const;
type Route = (typeof ROUTES)[number];

const NAV: { route: Route; label: MessageKey; icon: string }[] = [
  { route: 'home', label: 'nav.home', icon: '⌂' },
  { route: 'statement', label: 'nav.statement', icon: '≡' },
  { route: 'pay', label: 'nav.pay', icon: '⇄' },
  { route: 'schedules', label: 'nav.schedules', icon: '◷' },
  { route: 'reports', label: 'nav.reports', icon: '▤' },
  { route: 'fx', label: 'nav.fx', icon: '$' },
];

function readRoute(): Route {
  const r = location.hash.replace(/^#\/?/, '').split('?')[0];
  return (ROUTES as readonly string[]).includes(r) ? (r as Route) : 'home';
}

export function App() {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const i18n = useMemo(
    () =>
      makeI18n(lang, (l) => {
        persistLang(l);
        setLangState(l);
      }),
    [lang],
  );
  const [session, setSession] = useState<Session | null>(getSession);
  const [notice, setNotice] = useState<MessageKey | null>(null);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    setSessionLostHandler((reason) => {
      setSession(null);
      setNotice(reason === 'expired' ? 'login.expired' : 'login.invalid');
    });
  }, []);

  return (
    <I18nContext.Provider value={i18n}>
      {session ? (
        <Shell
          session={session}
          onLogout={async () => {
            await endSession();
            setSession(null);
          }}
        />
      ) : (
        <Login
          notice={notice}
          onLogin={(s) => {
            setNotice(null);
            setSession(s);
            location.hash = '#/home';
          }}
        />
      )}
    </I18nContext.Provider>
  );
}

function Countdown({ expiresAt }: { expiresAt: string }) {
  const { t } = useI18n();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const left = Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000));
  const mm = String(Math.floor(left / 60)).padStart(2, '0');
  const ss = String(left % 60).padStart(2, '0');
  return (
    <span className={`countdown ${left < 120 ? 'warn' : ''}`} title={t('session.expiresIn')}>
      ⏱ {mm}:{ss}
    </span>
  );
}

function Shell({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const { t } = useI18n();
  const [route, setRoute] = useState<Route>(readRoute);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);

  useEffect(() => {
    const onHash = () => setRoute(readRoute());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    api.customer().then(setCustomer, () => setCustomer(null));
  }, [session.customerId]);

  useEffect(() => {
    const ms = new Date(session.expiresAt).getTime() - Date.now();
    const id = setTimeout(expireLocally, Math.max(0, Math.min(ms, 2 ** 31 - 1)));
    return () => clearTimeout(id);
  }, [session.expiresAt]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [route]);

  const name = customer ? [customer.first_name, customer.last_name].filter(Boolean).join(' ') : session.customerId;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#/home">
            <img src="/favicon.svg" alt="" width={32} height={32} />
            <span>
              <strong>{t('app.name')}</strong>
              <small>{t('app.tagline')}</small>
            </span>
          </a>
          <div className="topbar-right">
            <LangSwitch />
            <Countdown expiresAt={session.expiresAt} />
            <button type="button" className="btn btn-small btn-light" onClick={onLogout}>
              {t('nav.logout')}
            </button>
          </div>
        </div>
        <nav className="tabs" aria-label="Menu">
          {NAV.map((n) => (
            <a key={n.route} href={`#/${n.route}`} className={route === n.route ? 'active' : ''} aria-current={route === n.route ? 'page' : undefined}>
              <span className="tab-icon" aria-hidden>
                {n.icon}
              </span>
              {t(n.label)}
            </a>
          ))}
        </nav>
      </header>

      <main className="content">
        <div className="greeting">
          <h1>
            {t('hello')}, {name}
          </h1>
          <span className="demo-pill">
            {t('login.demoBadge')} · <code>{session.customerId}</code>
          </span>
        </div>
        {route === 'home' && <Home />}
        {route === 'statement' && <Statement />}
        {route === 'pay' && <Pay />}
        {route === 'schedules' && <Schedules />}
        {route === 'reports' && <Reports />}
        {route === 'fx' && <Exchange />}
      </main>

      <Assistant open={assistantOpen} onToggle={() => setAssistantOpen((o) => !o)} />
    </div>
  );
}
