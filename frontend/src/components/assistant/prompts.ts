import {
    ArrowLeftRight,
    BadgeDollarSign,
    CreditCard,
    HandCoins,
    Headset,
    Receipt,
    TriangleAlert,
    Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import useSession from "@/contexts/session/use-session";

export type PromptKey = "balances" | "cardDue" | "lastTx" | "payCard" | "transfer" | "convert" | "declined" | "agent";

export type Prompt = {
    key: PromptKey;
    icon: LucideIcon;
    label: string;
    text: string;
    /** false: the text goes into the input so the customer can adjust the amount before sending. */
    send: boolean;
};

const last4 = (n: string | null | undefined) => n?.slice(-4);

/**
 * Pre-written prompts filled with the customer's own products (last 4 digits), so the assistant can answer
 * right away instead of asking "which account?". Only the ones that make sense for this customer are returned.
 */
export function useSuggestedPrompts(): Prompt[] {
    const { t } = useTranslation();
    const { balances } = useSession();

    const [first, second] = balances.accounts;
    const account = last4(first?.product_number);
    const account2 = last4(second?.product_number);
    const card = balances.credit_cards[0];
    const cardNo = last4(card?.product_number);
    const local = balances.accounts.find((a) => a.currency !== "USD")?.currency ?? "MXN";

    const make = (key: PromptKey, icon: LucideIcon, send: boolean, vars?: Record<string, string>): Prompt => ({
        key,
        icon,
        send,
        label: t(`assistant.prompts.${key}.label`),
        text: t(`assistant.prompts.${key}.text`, vars),
    });

    return [
        make("balances", Wallet, true),
        cardNo && make("cardDue", CreditCard, true, { card: cardNo }),
        make("lastTx", Receipt, true),
        cardNo && account && make("payCard", HandCoins, false, { card: cardNo, account, currency: card.currency }),
        account && account2 && make("transfer", ArrowLeftRight, false, { account, account2, currency: first.currency }),
        make("convert", BadgeDollarSign, true, { currency: local }),
        make("declined", TriangleAlert, true),
        make("agent", Headset, true),
    ].filter((p): p is Prompt => !!p);
}
