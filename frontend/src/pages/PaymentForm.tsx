import { api, getSession, type PaymentBody, type PaymentMethod, type Product } from '../api';
import { useI18n } from '../i18n';
import { TEST_CUSTOMERS } from '../testCustomers';
import { ErrorBox, money, useAsync } from '../ui';

export const CURRENCIES = ['USD', 'MXN', 'COP', 'ARS'];
const COUNTRIES = ['México', 'Colombia', 'Argentina'];
const FUNDS = ['Cuenta Corriente', 'Cuenta Ahorro', 'Tarjeta Débito'];
/** Destinos entre produtos do próprio cliente: contas, cartões de crédito (fatura) e empréstimos. */
const OWN_TARGETS = [...FUNDS, 'Tarjeta Crédito', 'Préstamo Personal', 'Préstamo Hipotecario'];

export interface PaymentDraft {
  method: PaymentMethod;
  source: string;
  amount: string;
  currency: string;
  description: string;
  destKind: 'person' | 'own' | 'external';
  toAccount: string;
  toProduct: string;
  benName: string;
  benAccount: string;
  benBank: string;
  benCountry: string;
  benDoc: string;
  pixKey: string;
  barcode: string;
  biller: string;
  dueDate: string;
}

export const emptyDraft = (method: PaymentMethod = 'transfer'): PaymentDraft => ({
  method,
  source: '',
  amount: '',
  currency: '',
  description: '',
  destKind: 'person',
  toAccount: '',
  toProduct: '',
  benName: '',
  benAccount: '',
  benBank: '',
  benCountry: COUNTRIES[0],
  benDoc: '',
  pixKey: '',
  barcode: '',
  biller: '',
  dueDate: '',
});

const opt = (v: string) => (v.trim() ? v.trim() : undefined);

/** Converte o rascunho no corpo da API (mesmo formato para /transfers, /pix, /bill-payments e destino do agendamento). */
export function toBody(d: PaymentDraft): PaymentBody {
  const body: PaymentBody = {
    source_product_id: d.source,
    amount: Number(d.amount),
    currency: opt(d.currency),
    description: opt(d.description),
  };
  if (d.method === 'transfer') {
    if (d.destKind === 'person') body.to_account_number = d.toAccount.trim();
    else if (d.destKind === 'own') body.to_product_id = d.toProduct;
    else
      body.beneficiary = {
        name: d.benName.trim(),
        account_number: d.benAccount.trim(),
        bank_name: opt(d.benBank),
        country: d.benCountry,
        document_number: opt(d.benDoc),
      };
  } else if (d.method === 'pix') {
    body.pix_key = d.pixKey.trim();
  } else {
    body.barcode = d.barcode.replace(/\s/g, '');
    body.biller_name = opt(d.biller);
    body.due_date = opt(d.dueDate);
  }
  return body;
}

/** Produtos que podem ser origem: contas e débito; para boleto, também cartão de crédito. */
function sourcesFor(products: Product[], method: PaymentMethod) {
  const types = method === 'bill_payment' ? [...FUNDS, 'Tarjeta Crédito'] : FUNDS;
  return products.filter((p) => types.includes(p.product_type));
}

export function useProducts() {
  return useAsync(() => api.products(), []);
}

export function PaymentFields({
  draft,
  onChange,
  products,
  productsError,
  showMethod = true,
}: {
  draft: PaymentDraft;
  onChange: (d: PaymentDraft) => void;
  products: Product[] | undefined;
  productsError?: unknown;
  showMethod?: boolean;
}) {
  const { t, tv, lang } = useI18n();
  const set = (patch: Partial<PaymentDraft>) => onChange({ ...draft, ...patch });
  const sources = sourcesFor(products ?? [], draft.method);

  return (
    <div className="stack">
      {showMethod && (
        <div className="segmented" role="tablist">
          {(['transfer', 'pix', 'bill_payment'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={draft.method === m}
              className={draft.method === m ? 'active' : ''}
              onClick={() => set({ method: m })}
            >
              {m === 'transfer' ? t('pay.transfer') : m === 'pix' ? t('pay.pix') : t('pay.bill')}
            </button>
          ))}
        </div>
      )}

      {productsError != null && <ErrorBox error={productsError} />}
      <label className="field">
        <span>{t('pay.source')}</span>
        <select value={draft.source} onChange={(e) => set({ source: e.target.value })} required>
          <option value="">{products ? t('pay.selectSource') : t('common.loading')}</option>
          {sources.map((p) => (
            <option key={p.product_id} value={p.product_id}>
              {tv('product', p.product_type)} {p.product_number ?? ''} ·{' '}
              {p.product_type === 'Tarjeta Crédito'
                ? `${t('home.available')} ${money(p.available_credit, p.currency, lang)}`
                : money(p.current_balance, p.currency, lang)}
              {p.status !== 'Active' ? ` (${p.status})` : ''}
            </option>
          ))}
        </select>
      </label>

      <div className="row">
        <label className="field grow">
          <span>{t('common.amount')}</span>
          <input
            type="number"
            inputMode="decimal"
            min="0.01"
            step="0.01"
            value={draft.amount}
            onChange={(e) => set({ amount: e.target.value })}
            required
          />
        </label>
        <label className="field">
          <span>
            {t('common.currency')} <small className="muted">({t('common.optional')})</small>
          </span>
          <select value={draft.currency} onChange={(e) => set({ currency: e.target.value })} title={t('pay.currencyHint')}>
            <option value="">—</option>
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
      </div>

      {draft.method === 'transfer' && (
        <>
          <div className="segmented small">
            {(['person', 'own', 'external'] as const).map((k) => (
              <button key={k} type="button" className={draft.destKind === k ? 'active' : ''} onClick={() => set({ destKind: k })}>
                {t(`pay.${k}`)}
              </button>
            ))}
          </div>
          {draft.destKind === 'person' ? (
            <label className="field">
              <span>{t('pay.toAccount')}</span>
              <input
                value={draft.toAccount}
                onChange={(e) => set({ toAccount: e.target.value })}
                inputMode="numeric"
                placeholder="0000000000"
                required
                list="test-accounts"
              />
              {/* Demo: atalhos com as contas dos outros clientes de teste. A prévia mostra quem recebe. */}
              <datalist id="test-accounts">
                {TEST_CUSTOMERS.filter((c) => c.id !== getSession()?.customerId).map((c) => (
                  <option key={c.id} value={c.account}>
                    {c.name}
                  </option>
                ))}
              </datalist>
              <small className="muted">
                {t('pay.hintAccount')}{' '}
                {TEST_CUSTOMERS.filter((c) => c.id !== getSession()?.customerId)
                  .map((c) => `${c.name.split(' ')[0]} ${c.account}`)
                  .join(' · ')}
              </small>
            </label>
          ) : draft.destKind === 'own' ? (
            <label className="field">
              <span>{t('pay.toOwn')}</span>
              <select value={draft.toProduct} onChange={(e) => set({ toProduct: e.target.value })} required>
                <option value="">{t('pay.selectOwn')}</option>
                {(products ?? [])
                  .filter((p) => p.product_id !== draft.source && p.status === 'Active' && OWN_TARGETS.includes(p.product_type))
                  .map((p) => (
                    <option key={p.product_id} value={p.product_id}>
                      {tv('product', p.product_type)} {p.product_number ?? ''} · {money(p.current_balance, p.currency, lang)}
                    </option>
                  ))}
              </select>
            </label>
          ) : (
            <div className="grid-2">
              <label className="field">
                <span>{t('pay.benName')}</span>
                <input value={draft.benName} onChange={(e) => set({ benName: e.target.value })} required />
              </label>
              <label className="field">
                <span>{t('pay.benAccount')}</span>
                <input value={draft.benAccount} onChange={(e) => set({ benAccount: e.target.value })} required />
              </label>
              <label className="field">
                <span>
                  {t('pay.benBank')} <small className="muted">({t('common.optional')})</small>
                </span>
                <input value={draft.benBank} onChange={(e) => set({ benBank: e.target.value })} />
              </label>
              <label className="field">
                <span>{t('pay.benCountry')}</span>
                <select value={draft.benCountry} onChange={(e) => set({ benCountry: e.target.value })}>
                  {COUNTRIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </>
      )}

      {draft.method === 'pix' && (
        <label className="field">
          <span>{t('pay.pixKey')}</span>
          <input value={draft.pixKey} onChange={(e) => set({ pixKey: e.target.value })} required />
          <small className="muted">{t('pay.hintPix')}</small>
        </label>
      )}

      {draft.method === 'bill_payment' && (
        <>
          <label className="field">
            <span>{t('pay.barcode')}</span>
            <input value={draft.barcode} onChange={(e) => set({ barcode: e.target.value })} inputMode="numeric" required />
          </label>
          <div className="grid-2">
            <label className="field">
              <span>
                {t('pay.biller')} <small className="muted">({t('common.optional')})</small>
              </span>
              <input value={draft.biller} onChange={(e) => set({ biller: e.target.value })} />
            </label>
            <label className="field">
              <span>
                {t('pay.dueDate')} <small className="muted">({t('common.optional')})</small>
              </span>
              <input type="date" value={draft.dueDate} onChange={(e) => set({ dueDate: e.target.value })} />
            </label>
          </div>
        </>
      )}

      <label className="field">
        <span>
          {t('common.description')} <small className="muted">({t('common.optional')})</small>
        </span>
        <input value={draft.description} maxLength={200} onChange={(e) => set({ description: e.target.value })} />
      </label>
    </div>
  );
}
