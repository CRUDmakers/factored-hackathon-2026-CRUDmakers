import { useState, type FormEvent } from 'react';
import { api, type CreateScheduleBody, type Schedule } from '../api';
import { useI18n } from '../i18n';
import { Card, dateTime, day, ErrorBox, Loading, money, useAsync } from '../ui';
import { describeCounterparty } from './Statement';
import { emptyDraft, PaymentFields, toBody, useProducts, type PaymentDraft } from './PaymentForm';

const FREQUENCIES = ['once', 'daily', 'weekly', 'monthly'] as const;

export function Schedules() {
  const { t, tv, lang } = useI18n();
  const list = useAsync(() => api.schedules(), []);
  const [showForm, setShowForm] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  /** Cancelar pede um segundo clique (sem window.confirm, que alguns navegadores embutidos bloqueiam). */
  const [confirmId, setConfirmId] = useState<string | null>(null);

  async function act(s: Schedule, action: 'pause' | 'resume' | 'cancel') {
    if (action === 'cancel' && confirmId !== s.scheduled_payment_id) {
      setConfirmId(s.scheduled_payment_id);
      return;
    }
    setConfirmId(null);
    setBusyId(s.scheduled_payment_id);
    setActionError(null);
    try {
      if (action === 'cancel') await api.cancelSchedule(s.scheduled_payment_id);
      else await api.updateSchedule(s.scheduled_payment_id, { status: action === 'pause' ? 'paused' : 'active' });
      list.reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="stack-lg">
      <Card
        title={t('sch.title')}
        actions={
          <button type="button" className="btn btn-primary btn-small" onClick={() => setShowForm((v) => !v)}>
            {showForm ? t('common.cancel') : `+ ${t('sch.new')}`}
          </button>
        }
      >
        {showForm && (
          <NewSchedule
            onCreated={() => {
              setShowForm(false);
              list.reload();
            }}
          />
        )}

        {actionError != null && <ErrorBox error={actionError} />}
        {list.error != null ? (
          <ErrorBox error={list.error} onRetry={list.reload} />
        ) : !list.data ? (
          <Loading />
        ) : list.data.length === 0 ? (
          <p className="muted">{t('common.empty')}</p>
        ) : (
          <ul className="schedule-list">
            {list.data.map((s) => (
              <li key={s.scheduled_payment_id}>
                <div className="sch-main">
                  <strong>
                    {tv('method', s.payment_method)} · {money(s.amount, s.currency, lang)}
                  </strong>
                  <small>
                    {describeCounterparty(s.destination)}
                    {s.description ? ` · ${s.description}` : ''}
                  </small>
                  <small className="muted">
                    {t(`sch.${s.frequency}`)} · {t('sch.nextRun')}: {dateTime(s.next_run_at, lang)} · {t('sch.executions')}: {s.executions_count}
                    {s.max_executions ? `/${s.max_executions}` : ''}
                    {s.end_date ? ` · ${t('sch.endDate')}: ${day(s.end_date, lang)}` : ''}
                  </small>
                  {s.last_result && (
                    <small className="muted">
                      {t('sch.lastResult')}: {s.last_result}
                    </small>
                  )}
                  <code className="muted small">{s.scheduled_payment_id}</code>
                </div>
                <div className="sch-side">
                  <span className={`badge badge-${s.status === 'active' ? 'ok' : s.status === 'paused' ? 'warn' : s.status === 'failed' ? 'bad' : 'muted'}`}>
                    {tv('sch.st', s.status)}
                  </span>
                  <div className="row">
                    {s.status === 'active' && (
                      <button className="btn btn-ghost btn-small" disabled={busyId === s.scheduled_payment_id} onClick={() => act(s, 'pause')}>
                        {t('sch.pause')}
                      </button>
                    )}
                    {s.status === 'paused' && (
                      <button className="btn btn-ghost btn-small" disabled={busyId === s.scheduled_payment_id} onClick={() => act(s, 'resume')}>
                        {t('sch.resume')}
                      </button>
                    )}
                    {(s.status === 'active' || s.status === 'paused') && (
                      <button className="btn btn-danger-ghost btn-small" disabled={busyId === s.scheduled_payment_id} onClick={() => act(s, 'cancel')}>
                        {confirmId === s.scheduled_payment_id ? t('sch.confirmCancel') : t('sch.cancel')}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function NewSchedule({ onCreated }: { onCreated: () => void }) {
  const { t } = useI18n();
  const products = useProducts();
  const [draft, setDraft] = useState<PaymentDraft>(() => emptyDraft());
  const [frequency, setFrequency] = useState<(typeof FREQUENCIES)[number]>('monthly');
  const [startAt, setStartAt] = useState('');
  const [endDate, setEndDate] = useState('');
  const [maxExec, setMaxExec] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const { source_product_id, amount, currency, description, ...destination } = toBody(draft);
    const body: CreateScheduleBody = {
      source_product_id,
      amount,
      currency,
      description,
      method: draft.method,
      destination,
      frequency,
      start_at: startAt ? new Date(startAt).toISOString() : undefined,
      end_date: endDate || undefined,
      max_executions: maxExec ? Number(maxExec) : undefined,
    };
    setBusy(true);
    setError(null);
    try {
      await api.createSchedule(body);
      onCreated();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack sub-form">
      <PaymentFields draft={draft} onChange={setDraft} products={products.data} productsError={products.error} />
      <div className="grid-2">
        <label className="field">
          <span>{t('sch.frequency')}</span>
          <select value={frequency} onChange={(e) => setFrequency(e.target.value as typeof frequency)}>
            {FREQUENCIES.map((f) => (
              <option key={f} value={f}>
                {t(`sch.${f}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>
            {t('sch.startAt')} <small className="muted">({t('common.optional')})</small>
          </span>
          <input type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} />
        </label>
        <label className="field">
          <span>
            {t('sch.endDate')} <small className="muted">({t('common.optional')})</small>
          </span>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
        <label className="field">
          <span>
            {t('sch.maxExec')} <small className="muted">({t('common.optional')})</small>
          </span>
          <input type="number" min="1" step="1" value={maxExec} onChange={(e) => setMaxExec(e.target.value)} />
        </label>
      </div>
      {error != null && <ErrorBox error={error} />}
      <button className="btn btn-primary" disabled={busy}>
        {busy ? t('common.loading') : t('sch.create')}
      </button>
    </form>
  );
}
