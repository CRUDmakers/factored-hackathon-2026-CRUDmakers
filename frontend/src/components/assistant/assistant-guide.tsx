import { useTranslation } from "react-i18next";
import { ArrowLeftRight, BadgeDollarSign, Ban, CalendarClock, CircleCheck, Headset, Receipt, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Prompt, PromptKey } from "./prompts";

type Capability = "balances" | "transactions" | "currency" | "payments" | "recurring" | "handoff";

/** Each capability of the assistant (ai-backend/ASSISTANT_GUIDE.md) with a prompt to try it. */
const CAPABILITIES: { key: Capability; icon: LucideIcon; example: PromptKey }[] = [
    { key: "balances", icon: Wallet, example: "balances" },
    { key: "transactions", icon: Receipt, example: "lastTx" },
    { key: "currency", icon: BadgeDollarSign, example: "convert" },
    { key: "payments", icon: ArrowLeftRight, example: "transfer" },
    { key: "recurring", icon: CalendarClock, example: "recurring" },
    { key: "handoff", icon: Headset, example: "agent" },
];

const STEPS = ["step1", "step2", "step3", "step4"] as const;
const TIPS = ["tip1", "tip2", "tip3"] as const;

export function AssistantGuide(props: { prompts: Prompt[]; onTry: (p: Prompt) => void; onStart: () => void }) {
    const { t } = useTranslation();

    return (
        <div className="flex flex-1 flex-col gap-6 overflow-y-auto px-4 py-5">
            <div className="flex flex-col gap-1">
                <h2 className="text-lg font-semibold">{t("guide.title")}</h2>
                <p className="text-muted-foreground text-sm">{t("guide.intro")}</p>
            </div>

            <section className="flex flex-col gap-2">
                <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                    {t("guide.capabilitiesTitle")}
                </h3>
                {CAPABILITIES.map(({ key, icon: Icon, example }) => {
                    const prompt = props.prompts.find((p) => p.key === example);
                    return (
                        <div key={key} className="flex gap-3 rounded-xl border p-3">
                            <span className="bg-primary/10 text-primary h-fit rounded-lg p-2">
                                <Icon className="size-4" />
                            </span>
                            <div className="flex min-w-0 flex-1 flex-col gap-1">
                                <strong className="text-sm">{t(`guide.cap.${key}.title`)}</strong>
                                <p className="text-muted-foreground text-xs">{t(`guide.cap.${key}.text`)}</p>
                                {prompt && (
                                    <button
                                        type="button"
                                        onClick={() => props.onTry(prompt)}
                                        className="bg-muted/60 hover:bg-primary/10 mt-1 flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-start text-xs transition"
                                    >
                                        <span className="italic">“{prompt.text}”</span>
                                        <span className="text-primary shrink-0 font-semibold">{t("guide.try")}</span>
                                    </button>
                                )}
                            </div>
                        </div>
                    );
                })}
            </section>

            <section className="flex flex-col gap-3">
                <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                    {t("guide.paymentsTitle")}
                </h3>
                <ol className="flex flex-col gap-3">
                    {STEPS.map((step, i) => (
                        <li key={step} className="flex gap-3 text-sm">
                            <span className="bg-gradient-primary flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white">
                                {i + 1}
                            </span>
                            <span>
                                <strong>{t(`guide.${step}.title`)}</strong>{" "}
                                <span className="text-muted-foreground">{t(`guide.${step}.text`)}</span>
                            </span>
                        </li>
                    ))}
                </ol>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                    {t("guide.tipsTitle")}
                </h3>
                {TIPS.map((tip) => (
                    <p key={tip} className="flex gap-2 text-sm">
                        <CircleCheck className="size-4 shrink-0 translate-y-0.5 text-emerald-600" />
                        {t(`guide.${tip}`)}
                    </p>
                ))}
            </section>

            <section className="bg-muted/60 flex gap-3 rounded-xl p-3 text-sm">
                <Ban className="text-muted-foreground size-4 shrink-0 translate-y-0.5" />
                <span>
                    <strong className="block">{t("guide.limitsTitle")}</strong>
                    <span className="text-muted-foreground">{t("guide.limitsText")}</span>
                </span>
            </section>

            <Button size="lg" onClick={props.onStart}>
                {t("guide.start")}
            </Button>
        </div>
    );
}
