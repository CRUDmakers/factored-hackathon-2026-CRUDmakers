import { useEffect, useState, type FormEvent } from "react";
import { api, type TransactionDetail as Detail } from "../api";
import { useI18n } from "../i18n";
import { Card, dateTime, day, ErrorBox, Loading, money, StatusBadge, useApiText, useAsync } from "../ui";

const TYPES = ["Purchase", "Withdrawal", "Transfer", "Payment", "Deposit", "Adjustment"];
const STATUSES = ["Approved", "Declined", "Pending", "Reversed"];
const CHANNELS = ["POS", "ATM", "Web", "App", "Branch", "Transfer"];
const PAGE = 20;

interface Filters {
    from: string;
    to: string;
    type: string;
    status: string;
    channel: string;
}
const EMPTY: Filters = { from: "", to: "", type: "", status: "", channel: "" };

/** Abre o detalhe direto por #/statement?tx=TRX-… (usado pelo comprovante). */
function txFromHash() {
    return new URLSearchParams(location.hash.split("?")[1] ?? "").get("tx");
}

export function Statement() {
    const { t, tv, lang } = useI18n();
    const apiText = useApiText();
    const [draft, setDraft] = useState<Filters>(EMPTY);
    const [filters, setFilters] = useState<Filters>(EMPTY);
    const [offset, setOffset] = useState(0);
    const [selected, setSelected] = useState<string | null>(txFromHash);

    const { data, error, loading, reload } = useAsync(
        () => api.transactions({ ...filters, limit: PAGE, offset }),
        [filters, offset]
    );

    function apply(e: FormEvent) {
        e.preventDefault();
        setOffset(0);
        setFilters(draft);
    }

    const page = Math.floor(offset / PAGE) + 1;
    const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;

    return (
        <div className="stack-lg">
            <Card title={t("tx.title")}>
                <form className="filters" onSubmit={apply}>
                    <label className="field">
                        <span>{t("common.from")}</span>
                        <input
                            type="date"
                            value={draft.from}
                            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
                        />
                    </label>
                    <label className="field">
                        <span>{t("common.to")}</span>
                        <input
                            type="date"
                            value={draft.to}
                            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
                        />
                    </label>
                    <Select
                        label={t("tx.type")}
                        value={draft.type}
                        onChange={(type) => setDraft({ ...draft, type })}
                        options={TYPES}
                        render={(v) => tv("type", v)}
                    />
                    <Select
                        label={t("common.status")}
                        value={draft.status}
                        onChange={(status) => setDraft({ ...draft, status })}
                        options={STATUSES}
                        render={(v) => tv("status", v)}
                    />
                    <Select
                        label={t("tx.channel")}
                        value={draft.channel}
                        onChange={(channel) => setDraft({ ...draft, channel })}
                        options={CHANNELS}
                    />
                    <div className="filter-actions">
                        <button className="btn btn-primary">{t("common.apply")}</button>
                        <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => {
                                setDraft(EMPTY);
                                setFilters(EMPTY);
                                setOffset(0);
                            }}
                        >
                            {t("common.clear")}
                        </button>
                    </div>
                </form>

                {error ? (
                    <ErrorBox error={error} onRetry={reload} />
                ) : !data ? (
                    <Loading />
                ) : (
                    <>
                        <p className="muted small">
                            {data.total} {t("tx.total")}
                            {loading && ` · ${t("common.loading")}`}
                        </p>
                        {data.items.length === 0 ? (
                            <p className="muted">{t("common.empty")}</p>
                        ) : (
                            <ul className="tx-list">
                                {data.items.map((tx) => (
                                    <li key={tx.transaction_id}>
                                        <button type="button" onClick={() => setSelected(tx.transaction_id)}>
                                            <span className={`tx-icon dir-${tx.direction}`} aria-hidden>
                                                {tx.direction === "in" ? "↓" : tx.direction === "out" ? "↑" : "±"}
                                            </span>
                                            <span className="tx-main">
                                                <strong>
                                                    {tx.merchant_name ||
                                                        tx.description ||
                                                        tv("type", tx.transaction_type)}
                                                </strong>
                                                <small>
                                                    {dateTime(tx.transaction_date, lang)} · {tv("cat", tx.category)} ·{" "}
                                                    {tx.channel ?? "—"}
                                                    {tx.transaction_city ? ` · ${tx.transaction_city}` : ""}
                                                    {tx.origin === "simulated" && (
                                                        <em className="tag-info"> {t("tx.simulated")}</em>
                                                    )}
                                                </small>
                                                {tx.status_reason && (
                                                    <small className="neg">
                                                        {apiText.reason(null, tx.status_reason, tx.response_code)}
                                                    </small>
                                                )}
                                            </span>
                                            <span className="tx-amount">
                                                <strong className={tx.direction === "in" ? "pos" : ""}>
                                                    {tx.direction === "in" ? "+" : tx.direction === "out" ? "−" : ""}
                                                    {money(tx.amount, tx.currency, lang)}
                                                </strong>
                                                <StatusBadge status={tx.transaction_status} />
                                            </span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                        <div className="pager">
                            <button
                                className="btn btn-ghost btn-small"
                                disabled={offset === 0 || loading}
                                onClick={() => setOffset(Math.max(0, offset - PAGE))}
                            >
                                ← {t("common.previous")}
                            </button>
                            <span>
                                {t("tx.page")} {page} / {pages}
                            </span>
                            <button
                                className="btn btn-ghost btn-small"
                                disabled={page >= pages || loading}
                                onClick={() => setOffset(offset + PAGE)}
                            >
                                {t("common.next")} →
                            </button>
                        </div>
                    </>
                )}
            </Card>

            {selected && (
                <TransactionModal
                    id={selected}
                    onClose={() => {
                        setSelected(null);
                        if (location.hash.includes("?")) history.replaceState(null, "", "#/statement");
                    }}
                />
            )}
        </div>
    );
}

function Select({
    label,
    value,
    onChange,
    options,
    render = (v) => v,
}: {
    label: string;
    value: string;
    onChange: (v: string) => void;
    options: string[];
    render?: (v: string) => string;
}) {
    const { t } = useI18n();
    return (
        <label className="field">
            <span>{label}</span>
            <select value={value} onChange={(e) => onChange(e.target.value)}>
                <option value="">{t("common.all")}</option>
                {options.map((o) => (
                    <option key={o} value={o}>
                        {render(o)}
                    </option>
                ))}
            </select>
        </label>
    );
}

function TransactionModal({ id, onClose }: { id: string; onClose: () => void }) {
    const { t } = useI18n();
    const { data, error, loading } = useAsync(() => api.transaction(id), [id]);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div
                className="modal"
                role="dialog"
                aria-modal="true"
                aria-label={t("tx.detail")}
                onClick={(e) => e.stopPropagation()}
            >
                <header className="card-head">
                    <h2>{t("tx.detail")}</h2>
                    <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        onClick={onClose}
                        aria-label={t("common.close")}
                    >
                        ✕
                    </button>
                </header>
                {loading && <Loading />}
                {error != null && <ErrorBox error={error} />}
                {data && <DetailBody tx={data} />}
            </div>
        </div>
    );
}

function DetailBody({ tx }: { tx: Detail }) {
    const { t, tv, lang } = useI18n();
    const apiText = useApiText();
    // balance_after está na moeda do produto, que pode diferir da moeda da operação.
    const products = useAsync(
        () => (tx.balance_after != null ? api.products() : Promise.resolve([])),
        [tx.transaction_id]
    );
    const productCurrency = products.data?.find((p) => p.product_id === tx.product_id)?.currency;
    const category =
        tx.transaction_category ??
        tx.merchant_category ??
        FALLBACK_CATEGORY[tx.transaction_type ?? ""] ??
        "Uncategorized";
    const s = tx.status;
    const coords = tx.location.coordinates;
    return (
        <div className="stack">
            <div className="detail-amount">
                <strong>{money(tx.amount, tx.currency, lang)}</strong>
                {tx.currency !== "USD" && tx.amount_usd != null && <small>≈ {money(tx.amount_usd, "USD", lang)}</small>}
                <StatusBadge status={s.status} />
            </div>

            <div
                className={`alert ${s.completed ? "alert-ok" : s.status === "Declined" ? "alert-error" : "alert-warn"}`}
            >
                <strong>{apiText.status(s.status, s.status_description)}</strong>
                {s.reason && (
                    <div>
                        {t("tx.reason")}: {apiText.reason(s.reason_code, s.reason)}{" "}
                        {s.reason_code && <code className="err-code">{s.reason_code}</code>}
                    </div>
                )}
                {s.response_code && <small className="muted"> ISO {s.response_code}</small>}
            </div>

            <div className="where">
                <h3>📍 {t("tx.where")}</h3>
                <p>{tx.location.summary}</p>
                {coords && (
                    <a
                        href={`https://www.openstreetmap.org/?mlat=${coords.latitude}&mlon=${coords.longitude}#map=16/${coords.latitude}/${coords.longitude}`}
                        target="_blank"
                        rel="noreferrer"
                    >
                        {t("tx.map")} ↗
                    </a>
                )}
            </div>

            <dl className="kv">
                <dt>{t("tx.id")}</dt>
                <dd>
                    <code>{tx.transaction_id}</code>
                </dd>
                <dt>{t("common.date")}</dt>
                <dd>{dateTime(tx.transaction_date, lang)}</dd>
                <dt>{t("tx.processDate")}</dt>
                <dd>{day(tx.process_date, lang)}</dd>
                <dt>{t("tx.type")}</dt>
                <dd>
                    {tv("type", tx.transaction_type)}
                    {tx.payment_method &&
                        tv("method", tx.payment_method) !== tv("type", tx.transaction_type) &&
                        ` · ${tv("method", tx.payment_method)}`}
                </dd>
                <dt>{t("tx.category")}</dt>
                <dd>{tv("cat", category)}</dd>
                <dt>{t("tx.product")}</dt>
                <dd>{tv("product", tx.product_type)}</dd>
                <dt>{t("tx.channel")}</dt>
                <dd>{tx.channel ?? "—"}</dd>
                {tx.merchant_name && (
                    <>
                        <dt>{t("tx.merchant")}</dt>
                        <dd>{tx.merchant_name}</dd>
                    </>
                )}
                {tx.description && (
                    <>
                        <dt>{t("common.description")}</dt>
                        <dd>{tx.description}</dd>
                    </>
                )}
                {tx.counterparty && (
                    <>
                        <dt>{t("tx.counterparty")}</dt>
                        <dd>{describeCounterparty(tx.counterparty)}</dd>
                    </>
                )}
                {tx.balance_after != null && (
                    <>
                        <dt>{t("tx.balanceAfter")}</dt>
                        <dd>{productCurrency ? money(tx.balance_after, productCurrency, lang) : "…"}</dd>
                    </>
                )}
            </dl>
            {tx.flagged_as_fraud && <div className="alert alert-error">{t("tx.fraud")}</div>}
        </div>
    );
}

const FALLBACK_CATEGORY: Record<string, string> = { Withdrawal: "Withdrawals", Transfer: "Transfers" };

export function describeCounterparty(c: Record<string, unknown>): string {
    const b = (c.beneficiary ?? {}) as Record<string, unknown>;
    const parts = [
        c.name,
        b.name,
        c.recipient_name,
        c.pix_key,
        c.biller_name,
        c.to_account_number,
        c.account_number,
        b.account_number,
        c.bank_name,
        b.bank_name,
        c.barcode,
        c.country,
        b.country,
        c.product_id,
        c.to_product_id,
    ]
        .filter((v) => typeof v === "string" && v)
        .map(String);
    return parts.length ? parts.join(" · ") : "—";
}
