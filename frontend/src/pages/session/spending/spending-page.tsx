import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, Download, Minus, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import type { TFunction } from "i18next";
import { cn } from "cn";
import { api, type Spending } from "@/api";
import { useAssistant } from "@/components/assistant/assistant";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import useSystem from "@/contexts/system/use-system";
import { useAsync } from "@/hooks/useAsync";
import { day, money, num } from "@/ui";

type Product = Spending["by_product"][number];
type Period = { months: number } | { from: string; to: string };

const PRESETS = [3, 6, 12];
// What the report counts as spending (backend/src/services/transactions.ts OUTFLOW_TYPES).
const OUTFLOW = ["Purchase", "Withdrawal", "Transfer", "Payment"];
/** "2026-04-01" → "01/04/2026": the date format the assistant prompts were tested with. */
const dmy = (iso: string) => iso.split("-").reverse().join("/");
const mask = (n: string | null) => (n ? `•••• ${n.slice(-4)}` : "");

/** "YYYY-MM-DD" is the last day of its month? */
const isMonthEnd = (iso: string) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m, 0).getDate() === d;
};

export default function SpendingPage() {
    const { t } = useTranslation();
    const { language } = useSystem();
    const lang = language === "es" ? "es" : "pt";
    const locale = lang === "es" ? "es-MX" : "pt-BR";

    const [period, setPeriod] = useState<Period>({ months: 6 });
    const [draft, setDraft] = useState({ from: "", to: "" });
    const [productId, setProductId] = useState("");
    const [openCategory, setOpenCategory] = useState("");
    const assistant = useAssistant();
    const { data, loading } = useAsync(() => api.spending({ ...period, product_id: productId }), [period, productId]);

    const usd = (v: number) => money(v, "USD", lang);
    const monthName = (ym: string) => {
        const [y, m] = ym.split("-").map(Number);
        return new Intl.DateTimeFormat(locale, { month: "short", year: "2-digit" }).format(new Date(y, m - 1, 1));
    };
    const label = (ns: "cat" | "product", key: string | null) =>
        key ? t(`${ns}.${key}` as "cat.Food", { defaultValue: key }) : t("spending.noProduct");
    const productLabel = (p: Product) => `${label("product", p.product_type)} ${mask(p.product_number)}`.trim();

    // The assistant's tools fetch the figures again: prompts carry only the period, card and category.
    const scope = (p?: Product) => {
        if (!p?.product_number) return "";
        const kind = p.product_type?.startsWith("Tarjeta")
            ? "onCard"
            : p.product_type?.startsWith("Cuenta")
              ? "onAccount"
              : "onProduct";
        return t(`spending.ai.${kind}`, { last4: p.product_number.slice(-4) });
    };
    const ask = (text: string) =>
        assistant.open({ prompt: { key: "spending", icon: Sparkles, label: text, text, send: true } });

    const applyCustom = (e: FormEvent) => {
        e.preventDefault();
        if (draft.from && draft.to && draft.from <= draft.to) setPeriod({ ...draft });
    };

    // Trend compares closed months only: a month still in progress would always look like a drop.
    const partial = data ? !isMonthEnd(data.period.to) : false;
    const closed = data ? (partial ? data.by_month.slice(0, -1) : data.by_month) : [];
    const last = closed.at(-1);
    const prev = closed.at(-2);
    const maxMonth = Math.max(1, ...(data?.by_month.map((m) => m.total_usd) ?? []));
    const maxCat = Math.max(1, ...(data?.by_category.map((c) => c.total_usd) ?? []));
    const top = data?.by_category[0];
    const selected = data?.by_product.find((p) => p.product_id === productId);

    return (
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 pb-24 sm:p-6 sm:pb-24">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
                <div className="flex flex-col gap-1">
                    <h1 className="text-2xl font-semibold">{t("spending.title")}</h1>
                    <span className="text-muted-foreground text-sm">{t("spending.subtitle")}</span>
                </div>
                <Button
                    size="lg"
                    className="sm:ms-auto"
                    disabled={!data}
                    onClick={() =>
                        data &&
                        ask(
                            t("spending.ai.analyzeText", {
                                from: dmy(data.period.from),
                                to: dmy(data.period.to),
                                scope: scope(selected),
                            })
                        )
                    }
                >
                    <Sparkles /> {t("spending.ai.analyze")}
                </Button>
            </div>

            {/* Filters */}
            <div className="flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1 text-xs font-medium">
                    {t("spending.card")}
                    <select
                        value={productId}
                        onChange={(e) => setProductId(e.target.value)}
                        className="border-input bg-background h-9 rounded-md border px-2.5 text-sm shadow-xs"
                    >
                        <option value="">{t("spending.allCards")}</option>
                        {data?.by_product
                            .filter((p) => p.product_id)
                            .map((p) => (
                                <option key={p.product_id} value={p.product_id!}>
                                    {productLabel(p)}
                                </option>
                            ))}
                    </select>
                </label>
                <ToggleGroup
                    aria-label={t("spending.period")}
                    multiple={false}
                    value={"months" in period ? [String(period.months)] : []}
                    onValueChange={(v) => v[0] && setPeriod({ months: Number(v[0]) })}
                    className="w-fit"
                >
                    {PRESETS.map((n) => (
                        <ToggleGroupItem key={n} value={String(n)}>
                            {t("spending.months", { count: n })}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <form onSubmit={applyCustom} className="flex flex-wrap items-end gap-2">
                    <label className="flex flex-col gap-1 text-xs font-medium">
                        {t("spending.from")}
                        <Input
                            type="date"
                            required
                            value={draft.from}
                            max={draft.to || undefined}
                            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
                        />
                    </label>
                    <label className="flex flex-col gap-1 text-xs font-medium">
                        {t("spending.to")}
                        <Input
                            type="date"
                            required
                            value={draft.to}
                            min={draft.from || undefined}
                            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
                        />
                    </label>
                    <Button type="submit" variant="outline">
                        {t("spending.apply")}
                    </Button>
                </form>
                <Button
                    className="sm:ms-auto"
                    disabled={!data}
                    onClick={() =>
                        data &&
                        downloadCsv(
                            data,
                            selected ? productLabel(selected) : t("spending.allCards"),
                            t,
                            label,
                            productLabel
                        )
                    }
                >
                    <Download /> {t("spending.download")}
                </Button>
            </div>

            {!data ? (
                <p className="text-muted-foreground text-sm">{t("loading")}</p>
            ) : (
                <div className={cn("flex flex-col gap-6 transition-opacity", loading && "opacity-60")}>
                    <span className="text-muted-foreground text-xs">
                        {t("spending.period")}: {day(data.period.from, lang)} – {day(data.period.to, lang)}
                        {selected && ` · ${productLabel(selected)}`}
                    </span>

                    {/* KPIs */}
                    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                        <Kpi label={t("spending.total")} value={usd(data.total_spent_usd)} />
                        <Kpi label={t("spending.average")} value={usd(data.monthly_average_usd)} />
                        <Kpi
                            label={t("spending.trend")}
                            value={last ? `${monthName(last.month)}: ${usd(last.total_usd)}` : "—"}
                            hint={
                                <Trend
                                    change={
                                        // change_pct is null after a zero month; zero to zero is still "flat".
                                        prev && last && prev.total_usd === last.total_usd
                                            ? 0
                                            : (last?.change_pct ?? null)
                                    }
                                    prevMonth={prev && monthName(prev.month)}
                                    lang={lang}
                                />
                            }
                        />
                        <Kpi
                            label={t("spending.topCategory")}
                            value={top ? label("cat", top.category) : "—"}
                            hint={top && `${num(top.share_pct, lang, 1)}% ${t("spending.share")}`}
                        />
                    </div>

                    <div className="grid gap-6 lg:grid-cols-2">
                        {/* Month-over-month */}
                        <Card>
                            <CardHeader>
                                <CardTitle>{t("spending.byMonth")}</CardTitle>
                            </CardHeader>
                            <CardContent className="flex flex-col gap-3">
                                <div className="flex h-56 items-stretch gap-1.5" role="list">
                                    {data.by_month.map((m, i) => {
                                        const inProgress = partial && i === data.by_month.length - 1;
                                        return (
                                            <div
                                                key={m.month}
                                                role="listitem"
                                                className="flex min-w-0 flex-1 flex-col items-center gap-1"
                                                title={`${monthName(m.month)}: ${usd(m.total_usd)}`}
                                            >
                                                <div className="flex w-full flex-1 flex-col items-center justify-end gap-1">
                                                    <span className="text-muted-foreground text-[10px] tabular-nums max-sm:hidden">
                                                        {num(m.total_usd, lang, 0)}
                                                    </span>
                                                    <div
                                                        className={cn(
                                                            "bg-primary w-full max-w-10 rounded-t-[4px]",
                                                            inProgress && "opacity-40"
                                                        )}
                                                        style={{
                                                            height: `${Math.max(1, (m.total_usd / maxMonth) * 100)}%`,
                                                        }}
                                                    />
                                                </div>
                                                <span className="text-xs">{monthName(m.month)}</span>
                                                <span className="text-muted-foreground h-4 text-[10px] tabular-nums">
                                                    {m.change_pct != null &&
                                                        !inProgress &&
                                                        `${m.change_pct > 0 ? "▲" : m.change_pct < 0 ? "▼" : ""} ${num(Math.abs(m.change_pct), lang, 0)}%`}
                                                </span>
                                            </div>
                                        );
                                    })}
                                </div>
                                {partial && (
                                    <p className="text-muted-foreground text-xs">
                                        {t("spending.partial", {
                                            month: monthName(data.by_month.at(-1)!.month),
                                            day: day(data.period.to, lang),
                                        })}
                                    </p>
                                )}
                            </CardContent>
                        </Card>

                        {/* Categories */}
                        <Card>
                            <CardHeader>
                                <CardTitle>{t("spending.byCategory")}</CardTitle>
                            </CardHeader>
                            <CardContent className="flex flex-col gap-3">
                                {data.by_category.length === 0 && (
                                    <p className="text-muted-foreground text-sm">{t("spending.empty")}</p>
                                )}
                                {data.by_category.map((c) => (
                                    <div key={c.category} className="flex flex-col gap-1">
                                        <button
                                            type="button"
                                            aria-expanded={openCategory === c.category}
                                            onClick={() =>
                                                setOpenCategory(openCategory === c.category ? "" : c.category)
                                            }
                                            className="hover:text-primary flex items-baseline justify-between gap-2 text-start text-sm"
                                        >
                                            <span className="font-medium">
                                                <ChevronDown
                                                    className={cn(
                                                        "me-1 inline size-3.5 transition-transform",
                                                        openCategory !== c.category && "-rotate-90"
                                                    )}
                                                />
                                                {label("cat", c.category)}{" "}
                                                <span className="text-muted-foreground text-xs font-normal">
                                                    {t("spending.tx", { count: c.count })}
                                                </span>
                                            </span>
                                            <span className="tabular-nums">
                                                {usd(c.total_usd)}{" "}
                                                <span className="text-muted-foreground text-xs">
                                                    {num(c.share_pct, lang, 1)}%
                                                </span>
                                            </span>
                                        </button>
                                        <div className="bg-muted h-2 overflow-hidden rounded-full">
                                            <div
                                                className="bg-primary h-full rounded-full"
                                                style={{ width: `${(c.total_usd / maxCat) * 100}%` }}
                                            />
                                        </div>
                                        {openCategory === c.category && (
                                            <CategoryTransactions
                                                category={c.category}
                                                from={data.period.from}
                                                to={data.period.to}
                                                productId={productId}
                                                productName={(id) => {
                                                    const p = data.by_product.find((x) => x.product_id === id);
                                                    return p ? productLabel(p) : "";
                                                }}
                                                lang={lang}
                                                onAsk={() =>
                                                    ask(
                                                        t("spending.ai.categoryText", {
                                                            category: label("cat", c.category),
                                                            from: dmy(data.period.from),
                                                            to: dmy(data.period.to),
                                                            scope: scope(selected),
                                                        })
                                                    )
                                                }
                                            />
                                        )}
                                    </div>
                                ))}
                            </CardContent>
                        </Card>
                    </div>

                    {/* Per card */}
                    <Card>
                        <CardHeader>
                            <CardTitle>{t("spending.byProduct")}</CardTitle>
                            <span className="text-muted-foreground text-xs">{t("spending.byProductHint")}</span>
                        </CardHeader>
                        <CardContent className="overflow-x-auto">
                            {data.by_product.length === 0 ? (
                                <p className="text-muted-foreground text-sm">{t("spending.empty")}</p>
                            ) : (
                                <table className="w-full text-sm tabular-nums">
                                    <thead className="text-muted-foreground text-xs">
                                        <tr className="border-b">
                                            <th className="py-2 pe-3 text-start font-medium">
                                                {t("spending.colProduct")}
                                            </th>
                                            {data.by_month.map((m) => (
                                                <th
                                                    key={m.month}
                                                    className="px-2 py-2 text-end font-medium whitespace-nowrap"
                                                >
                                                    {monthName(m.month)}
                                                </th>
                                            ))}
                                            <th className="py-2 ps-3 text-end font-medium">{t("spending.colTotal")}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.by_product.map((p) => (
                                            <tr
                                                key={p.product_id ?? "none"}
                                                className={cn(
                                                    "border-b last:border-0",
                                                    p.product_id && p.product_id === productId && "bg-primary/10"
                                                )}
                                            >
                                                <td className="py-2 pe-3">
                                                    <button
                                                        type="button"
                                                        disabled={!p.product_id}
                                                        onClick={() =>
                                                            setProductId(
                                                                p.product_id === productId ? "" : p.product_id!
                                                            )
                                                        }
                                                        className="hover:text-primary text-start font-medium whitespace-nowrap disabled:cursor-default disabled:hover:text-inherit"
                                                    >
                                                        {productLabel(p)}
                                                    </button>
                                                </td>
                                                {p.by_month.map((m) => (
                                                    <td
                                                        key={m.month}
                                                        className={cn(
                                                            "px-2 py-2 text-end",
                                                            !m.total_usd && "text-muted-foreground"
                                                        )}
                                                    >
                                                        {num(m.total_usd, lang, 0)}
                                                    </td>
                                                ))}
                                                <td className="py-2 ps-3 text-end font-semibold whitespace-nowrap">
                                                    {usd(p.total_usd)}{" "}
                                                    <span className="text-muted-foreground text-xs font-normal">
                                                        {num(p.share_pct, lang, 1)}%
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </CardContent>
                    </Card>
                </div>
            )}
        </div>
    );
}

/** The transactions behind one category of the report: same period, card and rules (approved outflows). */
function CategoryTransactions(props: {
    category: string;
    from: string;
    to: string;
    productId: string;
    productName: (productId: string | null) => string;
    lang: "es" | "pt";
    onAsk: () => void;
}) {
    const { t } = useTranslation();
    const { category, from, to, productId, lang } = props;
    const { data } = useAsync(
        () => api.transactions({ category, from, to, product_id: productId, status: "Approved", limit: 200 }),
        [category, from, to, productId]
    );
    const rows = data?.items.filter((tx) => OUTFLOW.includes(tx.transaction_type ?? ""));

    return (
        <div className="bg-muted/40 mt-1 flex flex-col gap-2 rounded-lg p-3">
            {!rows ? (
                <span className="text-muted-foreground text-xs">{t("loading")}</span>
            ) : (
                <ul className="flex flex-col divide-y">
                    {rows.map((tx) => (
                        <li key={tx.transaction_id} className="flex items-baseline gap-3 py-1.5 text-xs">
                            <span className="text-muted-foreground w-16 shrink-0 tabular-nums">
                                {day(tx.transaction_date, lang)}
                            </span>
                            <span className="flex min-w-0 flex-1 flex-col">
                                <span className="truncate font-medium">
                                    {tx.merchant_name ?? tx.description ?? tx.transaction_type}
                                </span>
                                <span className="text-muted-foreground truncate">
                                    {props.productName(tx.product_id)}
                                </span>
                            </span>
                            <span className="flex flex-col text-end tabular-nums">
                                <span>{money(tx.amount, tx.currency, lang)}</span>
                                {tx.currency !== "USD" && tx.amount_usd != null && (
                                    <span className="text-muted-foreground">{money(tx.amount_usd, "USD", lang)}</span>
                                )}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
            {data && data.total > data.items.length && (
                <span className="text-muted-foreground text-xs">
                    {t("spending.drill.partial", { shown: data.items.length, total: data.total })}
                </span>
            )}
            <Button variant="outline" size="sm" className="w-fit" onClick={props.onAsk}>
                <Sparkles /> {t("spending.ai.askCategory")}
            </Button>
        </div>
    );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: React.ReactNode }) {
    return (
        <div className="bg-card flex flex-col gap-1 rounded-xl border p-4 shadow-xs">
            <span className="text-muted-foreground text-xs">{label}</span>
            <strong className="truncate text-lg">{value}</strong>
            {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
        </div>
    );
}

function Trend({ change, prevMonth, lang }: { change: number | null; prevMonth?: string; lang: "es" | "pt" }) {
    const { t } = useTranslation();
    if (change == null || !prevMonth) return <>{t("spending.noTrend")}</>;
    const pct = num(Math.abs(change), lang, 1);
    const [Icon, text] =
        change > 0
            ? [TrendingUp, t("spending.up", { pct, month: prevMonth })]
            : change < 0
              ? [TrendingDown, t("spending.down", { pct, month: prevMonth })]
              : [Minus, t("spending.flat", { month: prevMonth })];
    return (
        <span className="inline-flex items-center gap-1">
            <Icon className="size-3.5" /> {text}
        </span>
    );
}

/** The report the page shows, as a CSV that opens in Excel (BOM for the accents). */
function downloadCsv(
    data: Spending,
    scope: string,
    t: TFunction,
    label: (ns: "cat" | "product", key: string | null) => string,
    productLabel: (p: Product) => string
) {
    const months = data.by_month.map((m) => m.month);
    const rows: (string | number)[][] = [
        [t("spending.period"), data.period.from, data.period.to],
        [t("spending.card"), scope],
        [],
        [t("spending.csvMonth"), "USD", `${t("spending.colChange")} %`],
        ...data.by_month.map((m) => [m.month, m.total_usd, m.change_pct ?? ""]),
        [],
        [t("spending.csvCategory"), "USD", "%", t("spending.csvTransactions")],
        ...data.by_category.map((c) => [label("cat", c.category), c.total_usd, c.share_pct, c.count]),
        [],
        [t("spending.colProduct"), ...months, `${t("spending.colTotal")} USD`, "%"],
        ...data.by_product.map((p) => [
            productLabel(p),
            ...p.by_month.map((m) => m.total_usd),
            p.total_usd,
            p.share_pct,
        ]),
    ];
    const csv = "﻿" + rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `gastos_${data.period.from}_${data.period.to}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
