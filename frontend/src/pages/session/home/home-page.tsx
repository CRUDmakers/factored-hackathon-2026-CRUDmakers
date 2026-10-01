import { useTranslation } from "react-i18next";
import { ArrowLeftRight, BookOpen, ChevronRight, CreditCard, HandCoins, Landmark, ShieldCheck } from "lucide-react";
import { cn } from "cn";
import { AssistantAvatar, useAssistant } from "@/components/assistant/assistant";
import { useSuggestedPrompts } from "@/components/assistant/prompts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import useSession from "@/contexts/session/use-session";
import useSystem from "@/contexts/system/use-system";
import { money, num } from "@/ui";

const mask = (n: string | null) => (n ? `•••• ${n.slice(-4)}` : "");

export default function HomePage() {
    const { t } = useTranslation();
    const { language } = useSystem();
    const lang = language === "es" ? "es" : "pt";
    const { customer, balances } = useSession();
    const assistant = useAssistant();
    const prompts = useSuggestedPrompts();
    const transfer = prompts.find((p) => p.key === "transfer");

    const today = new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "pt-BR", { dateStyle: "full" }).format(new Date());

    return (
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 pb-24 sm:p-6 sm:pb-24">
            {/* Greeting */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
                <div className="flex flex-col gap-1">
                    <span className="text-muted-foreground text-sm first-letter:uppercase">{today}</span>
                    <h1 className="text-2xl font-semibold">
                        {customer.first_name ? t("home.hello", { name: customer.first_name }) : t("home.helloAnon")}
                    </h1>
                </div>
                <div className="flex gap-2 sm:ms-auto">
                    {transfer && (
                        <Button variant="outline" size="lg" onClick={() => assistant.open({ prompt: transfer })}>
                            <ArrowLeftRight /> {t("home.transfer")}
                        </Button>
                    )}
                    <Button size="lg" onClick={() => assistant.open()}>
                        <AssistantAvatar className="size-5 ring-0 [&_svg]:size-3" /> {t("home.askAssistant")}
                    </Button>
                </div>
            </div>

            {/* Hero */}
            <section className="bg-gradient-primary relative overflow-hidden rounded-2xl p-6 text-white shadow-lg">
                <div className="absolute -end-16 -top-16 size-56 rounded-full bg-white/10" aria-hidden />
                <div className="absolute -end-4 -bottom-24 size-56 rounded-full bg-white/5" aria-hidden />
                <div className="relative flex flex-col gap-5">
                    <div className="flex flex-col gap-1">
                        <span className="text-sm text-white/80">{t("home.netWorth")}</span>
                        <strong className="text-4xl font-bold tracking-tight">
                            {money(balances.net_worth_usd, "USD", lang)}
                        </strong>
                        <span className="text-xs text-white/70">{t("home.netWorthHint")}</span>
                    </div>
                    <div className="flex flex-wrap gap-3">
                        {balances.totals_by_currency.map((c) => (
                            <div
                                key={c.currency}
                                className="flex gap-6 rounded-xl bg-white/12 px-4 py-3 backdrop-blur-sm"
                            >
                                <Stat
                                    label={`${t("home.available")} · ${c.currency}`}
                                    value={money(c.available_funds, c.currency, lang)}
                                />
                                <Stat
                                    label={`${t("home.debt")} · ${c.currency}`}
                                    value={money(c.debt, c.currency, lang)}
                                />
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            {/* Quick actions through the assistant */}
            <section className="flex flex-col gap-3">
                <div className="flex flex-col">
                    <h2 className="font-semibold">{t("home.quickTitle")}</h2>
                    <span className="text-muted-foreground text-sm">{t("home.quickSubtitle")}</span>
                </div>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    {prompts.slice(0, 4).map((p) => {
                        const Icon = p.icon;
                        return (
                            <button
                                key={p.key}
                                type="button"
                                onClick={() => assistant.open({ prompt: p })}
                                className="bg-card hover:border-primary/40 group flex flex-col gap-3 rounded-xl border p-4 text-start shadow-xs transition hover:-translate-y-0.5 hover:shadow-md"
                            >
                                <span className="bg-primary/10 text-primary group-hover:bg-primary w-fit rounded-lg p-2 transition group-hover:text-white">
                                    <Icon className="size-5" />
                                </span>
                                <span className="text-sm font-semibold">{p.label}</span>
                            </button>
                        );
                    })}
                </div>
            </section>

            <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
                <div className="flex flex-col gap-6">
                    {/* Accounts */}
                    <Card>
                        <CardHeader>
                            <CardTitle>{t("home.accounts")}</CardTitle>
                        </CardHeader>
                        <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                            {balances.accounts.length === 0 && <Empty />}
                            {balances.accounts.map((a) => (
                                <div key={a.product_id} className="flex flex-col gap-3 rounded-xl border p-4">
                                    <div className="flex items-center gap-2">
                                        <span className="bg-primary/10 text-primary rounded-lg p-2">
                                            <Landmark className="size-4" />
                                        </span>
                                        <div className="flex min-w-0 flex-col">
                                            <span className="truncate text-sm font-medium">{a.product_type}</span>
                                            <span className="text-muted-foreground text-xs">
                                                {mask(a.product_number)}
                                            </span>
                                        </div>
                                    </div>
                                    <strong className="text-xl">{money(a.balance, a.currency, lang)}</strong>
                                </div>
                            ))}
                        </CardContent>
                    </Card>

                    {/* Loans */}
                    <Card>
                        <CardHeader>
                            <CardTitle>{t("home.loans")}</CardTitle>
                        </CardHeader>
                        <CardContent className="flex flex-col divide-y">
                            {balances.loans.length === 0 && <Empty />}
                            {balances.loans.map((l) => (
                                <div key={l.product_id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                                    <span className="rounded-lg bg-amber-100 p-2 text-amber-700">
                                        <HandCoins className="size-4" />
                                    </span>
                                    <div className="flex min-w-0 flex-1 flex-col">
                                        <span className="truncate text-sm font-medium">{l.product_type}</span>
                                        <span className="text-muted-foreground text-xs">
                                            {t("home.rate")}:{" "}
                                            {l.interest_rate != null ? `${num(l.interest_rate, lang)}%` : "—"}
                                            {!!l.days_past_due && (
                                                <span className="text-destructive">
                                                    {" "}
                                                    · {t("home.overdue", { days: l.days_past_due })}
                                                </span>
                                            )}
                                        </span>
                                    </div>
                                    <div className="flex flex-col text-end">
                                        <span className="text-muted-foreground text-xs">{t("home.outstanding")}</span>
                                        <strong className="text-sm">
                                            {money(l.outstanding_balance, l.currency, lang)}
                                        </strong>
                                    </div>
                                </div>
                            ))}
                        </CardContent>
                    </Card>
                </div>

                <div className="flex flex-col gap-6">
                    {/* Credit cards */}
                    <Card>
                        <CardHeader>
                            <CardTitle>{t("home.cards")}</CardTitle>
                        </CardHeader>
                        <CardContent className="flex flex-col gap-5">
                            {balances.credit_cards.length === 0 && <Empty />}
                            {balances.credit_cards.map((c) => {
                                const used =
                                    c.utilization_pct ??
                                    (c.credit_limit > 0 ? (c.invoice_amount / c.credit_limit) * 100 : 100);
                                return (
                                    <div key={c.product_id} className="flex flex-col gap-2.5">
                                        <div className="flex items-center gap-2">
                                            <CreditCard className="text-primary size-4" />
                                            <span className="text-sm font-medium">{mask(c.product_number)}</span>
                                            {!!c.days_past_due && (
                                                <Badge variant="destructive" className="ms-auto">
                                                    {t("home.overdue", { days: c.days_past_due })}
                                                </Badge>
                                            )}
                                        </div>
                                        <div className="flex items-baseline justify-between gap-2">
                                            <span className="text-muted-foreground text-xs">{t("home.invoice")}</span>
                                            <strong>{money(c.invoice_amount, c.currency, lang)}</strong>
                                        </div>
                                        <Progress
                                            value={Math.min(100, Math.max(0, used))}
                                            aria-label={t("home.used")}
                                            className={cn(
                                                used >= 90 && "[&_[data-slot=progress-indicator]]:bg-destructive"
                                            )}
                                        />
                                        <div className="text-muted-foreground flex justify-between text-xs">
                                            <span>
                                                {t("home.used")}: {num(used, lang, 0)}%
                                            </span>
                                            <span>
                                                {t("home.availableCredit")}:{" "}
                                                {money(c.available_credit, c.currency, lang)}
                                            </span>
                                        </div>
                                    </div>
                                );
                            })}
                        </CardContent>
                    </Card>

                    {/* Guide */}
                    <button
                        type="button"
                        onClick={() => assistant.open({ view: "guide" })}
                        className="bg-card hover:border-primary/40 flex items-center gap-4 rounded-xl border p-4 text-start shadow-xs transition hover:shadow-md"
                    >
                        <AssistantAvatar className="size-11" />
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <strong className="text-sm">{t("home.guideTitle")}</strong>
                            <span className="text-muted-foreground text-xs">{t("home.guideText")}</span>
                            <span className="text-primary mt-1 flex items-center gap-1 text-xs font-semibold">
                                <BookOpen className="size-3.5" /> {t("home.guideButton")}
                            </span>
                        </span>
                        <ChevronRight className="text-muted-foreground size-4" />
                    </button>

                    {/* Safety */}
                    <div className="flex gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">
                        <ShieldCheck className="size-5 shrink-0" />
                        <span className="flex flex-col gap-0.5">
                            <strong className="text-sm">{t("home.safeTitle")}</strong>
                            <span className="text-xs">{t("home.safeText")}</span>
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
}

function Stat({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex flex-col">
            <span className="text-xs text-white/75">{label}</span>
            <strong className="text-base">{value}</strong>
        </div>
    );
}

function Empty() {
    const { t } = useTranslation();
    return <p className="text-muted-foreground text-sm">{t("home.noItems")}</p>;
}
