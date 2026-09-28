import { useState, type FormEvent } from 'react';
import { api, type PaymentBody, type PaymentResult } from '../api';
import { useI18n } from '../i18n';
import { Card, dateTime, ErrorBox, money, num, StatusBadge, useApiText } from '../ui';
import { describeCounterparty } from './Statement';
import { emptyDraft, PaymentFields, toBody, useProducts, type PaymentDraft } from './PaymentForm';

type Step = { kind: 'form' } | { kind: 'preview'; body: PaymentBody; result: PaymentResult } | { kind: 'receipt'; result: PaymentResult };

/**
 * Confirmação obrigatória em duas etapas:
 * 1) POST ...?dry_run=true -> mostra a prévia (nada é gravado);
 * 2) só no "Confirmar" o mesmo corpo é enviado sem dry_run -> comprovante com o status real.
 */
export function Pay() {
  const { t, lang } = useI18n();
  const products = useProducts();
  const [draft, setDraft] = useState<PaymentDraft>(() => emptyDraft());
  const [step, setStep] = useState<Step>({ kind: 'form' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function preview(e: FormEvent) {
    e.preventDefault();
    const body = toBody(draft);
    setBusy(true);
    setError(null);
    try {
      const result = await api.pay(draft.method, body, true);
      setStep({ kind: 'preview', body, result });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (step.kind !== 'preview') return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.pay(draft.method, step.body, false);
      setStep({ kind: 'receipt', result });
      products.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function restart() {
    setDraft((d) => ({ ...emptyDraft(d.method), source: d.source }));
    setStep({ kind: 'form' });
    setError(null);
  }

  return (
    <div className="pay-layout">
      <Card title={t('pay.title')}>
        <ol className="steps" aria-label="steps">
          <li className={step.kind === 'form' ? 'active' : 'done'}>1</li>
          <li className={step.kind === 'preview' ? 'active' : step.kind === 'receipt' ? 'done' : ''}>2</li>
          <li className={step.kind === 'receipt' ? 'active' : ''}>✓</li>
        </ol>

        {step.kind === 'form' && (
          <form onSubmit={preview} className="stack">
            <PaymentFields draft={draft} onChange={setDraft} products={products.data} productsError={products.error} />
            {error != null && <ErrorBox error={error} />}
            <button className="btn btn-primary btn-block" disabled={busy}>
              {busy ? t('common.loading') : t('pay.continue')}
            </button>
          </form>
        )}

        {step.kind === 'preview' && (
          <div className="stack">
            <h3>{t('pay.previewTitle')}</h3>
            <p className="muted small">{t('pay.previewNote')}</p>
            <ResultSummary result={step.result} />
            {error != null && <ErrorBox error={error} />}
            <div className="row">
              <button type="button" className="btn btn-ghost grow" onClick={() => setStep({ kind: 'form' })} disabled={busy}>
                ← {t('pay.edit')}
              </button>
              <button
                type="button"
                className={`btn grow ${step.result.completed ? 'btn-primary' : 'btn-danger'}`}
                onClick={confirm}
                disabled={busy}
              >
                {busy ? t('common.loading') : step.result.completed ? t('pay.confirm') : t('pay.confirmAnyway')}
              </button>
            </div>
          </div>
        )}

        {step.kind === 'receipt' && (
          <div className="stack receipt">
            <div className={`receipt-head ${step.result.completed ? 'ok' : 'bad'}`}>
              <span aria-hidden>{step.result.completed ? '✓' : '✕'}</span>
              <h3>{step.result.completed ? t('pay.receiptApproved') : t('pay.receiptDeclined')}</h3>
            </div>
            <ResultSummary result={step.result} />
            <dl className="kv">
              <dt>{t('pay.txId')}</dt>
              <dd>
                <code>{step.result.transaction_id ?? '—'}</code>
              </dd>
              <dt>{t('common.date')}</dt>
              <dd>{dateTime(step.result.transaction_date, lang)}</dd>
            </dl>
            <div className="row">
              {step.result.transaction_id && (
                <a className="btn btn-ghost grow" href={`#/statement?tx=${step.result.transaction_id}`}>
                  {t('pay.viewDetail')}
                </a>
              )}
              <button type="button" className="btn btn-primary grow" onClick={restart}>
                {t('pay.new')}
              </button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function ResultSummary({ result }: { result: PaymentResult }) {
  const { t, tv, lang } = useI18n();
  const apiText = useApiText();
  const src = result.source;
  const dest = result.counterparty?.destination_amount;
  return (
    <div className="stack">
      <div className={`alert ${result.completed ? 'alert-ok' : 'alert-error'}`}>
        <div className="row-between">
          <strong>
            {result.preview ? (result.completed ? t('pay.predictedOk') : t('pay.predictedDecline')) : apiText.status(result.status, result.status_description)}
          </strong>
          <StatusBadge status={result.status} />
        </div>
        {result.reason && (
          <div>
            {t('tx.reason')}: {apiText.reason(result.reason_code, result.reason)} {result.reason_code && <code className="err-code">{result.reason_code}</code>}
          </div>
        )}
        {result.decline_detail && <div className="small">{result.decline_detail}</div>}
      </div>

      <dl className="kv">
        <dt>{t('common.amount')}</dt>
        <dd>
          <strong>{money(result.amount, result.currency, lang)}</strong> · {tv('method', result.method)}
        </dd>
        <dt>{t('pay.source')}</dt>
        <dd>
          {tv('product', src.product_type)} <code>{src.product_id}</code>
        </dd>
        <dt>{t('pay.debited')}</dt>
        <dd>{money(src.debited_amount, src.currency, lang)}</dd>
        {result.exchange && (
          <>
            <dt>{t('pay.exchange')}</dt>
            <dd>
              1 {result.exchange.from} = {num(result.exchange.rate, lang, 6)} {result.exchange.to}{' '}
              <small className="muted">({result.exchange.rate_date})</small>
            </dd>
          </>
        )}
        <dt>{t('pay.balanceAfter')}</dt>
        <dd>{money(src.balance_after, src.currency, lang)}</dd>
        {result.counterparty && (
          <>
            <dt>{t('pay.recipient')}</dt>
            <dd>{describeCounterparty(result.counterparty)}</dd>
          </>
        )}
        {dest && (
          <>
            <dt>{t('pay.destAmount')}</dt>
            <dd>
              {money(dest.amount, dest.currency, lang)}{' '}
              <small className="muted">
                ({t('fx.rate')} {num(dest.rate, lang, 6)} · {dest.rate_date})
              </small>
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}
