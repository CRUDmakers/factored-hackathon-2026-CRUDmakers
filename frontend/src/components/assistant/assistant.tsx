import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
    BookOpen,
    Download,
    FileSpreadsheet,
    FileText,
    Headset,
    LoaderCircle,
    Lightbulb,
    Maximize2,
    Minimize2,
    RotateCcw,
    SendHorizontal,
    ShieldCheck,
    Sparkles,
    X,
} from "lucide-react";
import { cn } from "cn";
import { api, ApiError, downloadChatFile, type ChatFile, type ChatRequest, type ChatResponse } from "@/api";
import { Button } from "@/components/ui/button";
import useSession from "@/contexts/session/use-session";
import { AssistantGuide } from "./assistant-guide";
import { useSuggestedPrompts, type Prompt } from "./prompts";

type View = "chat" | "guide";
type Bubble = { id: number; from: "user" | "bot" | "error"; text: string; res?: ChatResponse };
type OpenOptions = { view?: View; prompt?: Prompt };

const AssistantContext = createContext<{ open: (opts?: OpenOptions) => void }>(null!);

/** Opens the assistant from anywhere in the session (sidebar, home quick actions, guide card). */
export const useAssistant = () => useContext(AssistantContext);

/** The assistant's mark: the same gradient as the brand, with a sparkle. */
export function AssistantAvatar({ className }: { className?: string }) {
    return (
        <span
            aria-hidden
            className={cn(
                "bg-gradient-primary inline-flex size-9 shrink-0 items-center justify-center rounded-full text-white shadow-sm ring-2 ring-white/70",
                className
            )}
        >
            <Sparkles className="size-[55%]" strokeWidth={2.2} />
        </span>
    );
}

/** Chat with the AI backend (Backend 2). Contract: ai-backend/CHAT_API.md. */
export function AssistantProvider({ children }: { children: React.ReactNode }) {
    const { t } = useTranslation();
    const { customer, reloadBalances } = useSession();
    const prompts = useSuggestedPrompts();

    const [isOpen, setOpen] = useState(false);
    const [view, setView] = useState<View>("chat");
    const [expanded, setExpanded] = useState(false);
    const [showChips, setShowChips] = useState(false);
    const [bubbles, setBubbles] = useState<Bubble[]>([]);
    const [draft, setDraft] = useState("");
    const [busy, setBusy] = useState(false);
    const [last, setLast] = useState<ChatResponse | null>(null);

    const conversationId = useRef<string | undefined>(undefined);
    const nextId = useRef(0);
    const bottom = useRef<HTMLDivElement>(null);
    const input = useRef<HTMLTextAreaElement>(null);

    const push = (from: Bubble["from"], text: string, res?: ChatResponse) =>
        setBubbles((b) => [...b, { id: nextId.current++, from, text, res }]);

    const send = useCallback(
        async (body: Omit<ChatRequest, "conversation_id">, shown: string) => {
            push("user", shown);
            setShowChips(false);
            setBusy(true);
            try {
                const res = await api.chat({ ...body, conversation_id: conversationId.current });
                conversationId.current = res.conversation_id;
                setLast(res);
                push("bot", res.message, res);
                // A confirmed payment changes the balances every screen shows.
                if (body.confirmation?.decision === "approve") reloadBalances();
            } catch (err) {
                // 404: the server doesn't know this conversation any more -> the next message starts a new one.
                if (err instanceof ApiError && err.status === 404) conversationId.current = undefined;
                push("error", err instanceof ApiError && err.status !== 404 ? err.message : t("assistant.error"));
            } finally {
                setBusy(false);
            }
        },
        [reloadBalances, t]
    );

    const runPrompt = useCallback(
        (prompt: Prompt) => {
            setView("chat");
            if (prompt.send && !busy) return void send({ message: prompt.text }, prompt.text);
            setDraft(prompt.text);
            requestAnimationFrame(() => input.current?.focus());
        },
        [busy, send]
    );

    const open = useCallback(
        (opts: OpenOptions = {}) => {
            setOpen(true);
            setView(opts.view ?? "chat");
            if (opts.prompt) runPrompt(opts.prompt);
        },
        [runPrompt]
    );

    const reset = () => {
        conversationId.current = undefined;
        setBubbles([]);
        setLast(null);
        setDraft("");
        setView("chat");
    };

    useEffect(() => {
        bottom.current?.scrollIntoView({ block: "end" });
    }, [bubbles, busy]);

    // Grow with the text, also when a suggestion fills it programmatically.

    useEffect(() => {
        const el = input.current;

        if (!el) return;

        el.style.height = "auto";

        el.style.height = `${el.scrollHeight}px`;
    }, [draft, view]);

    useEffect(() => {
        if (!isOpen) return;
        if (view === "chat") input.current?.focus();
        const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [isOpen, view]);

    const submit = () => {
        const text = draft.trim();
        if (!text || busy) return;
        setDraft("");
        send({ message: text }, text);
    };

    const pending = !busy && last?.status === "awaiting_confirmation" ? last.pending_action : null;
    const decide = (decision: "approve" | "reject") =>
        pending &&
        send(
            { confirmation: { action_id: pending.action_id, decision } },
            t(decision === "approve" ? "assistant.confirm" : "assistant.cancel")
        );

    return (
        <AssistantContext.Provider value={{ open }}>
            {children}

            {/* Launcher */}
            <button
                type="button"
                onClick={() => (isOpen ? setOpen(false) : open())}
                aria-expanded={isOpen}
                aria-controls="assistant-panel"
                aria-label={t(isOpen ? "assistant.close" : "assistant.open")}
                className={cn(
                    "bg-card text-foreground fixed right-5 bottom-5 z-50 flex items-center gap-2.5 rounded-full border py-1.5 ps-1.5 pe-4 shadow-lg transition hover:-translate-y-0.5 hover:shadow-xl",
                    isOpen && "max-sm:hidden"
                )}
            >
                {isOpen ? (
                    <span className="bg-muted inline-flex size-9 items-center justify-center rounded-full">
                        <X className="size-4" />
                    </span>
                ) : (
                    <span className="relative">
                        <AssistantAvatar />
                        <span className="absolute -end-0.5 -top-0.5 size-3 rounded-full border-2 border-white bg-emerald-500" />
                    </span>
                )}
                <span className="text-sm font-semibold">{t("nav.assistant")}</span>
            </button>

            {isOpen && (
                <section
                    id="assistant-panel"
                    role="dialog"
                    aria-label={t("assistant.name")}
                    className={cn(
                        "bg-background animate-in fade-in slide-in-from-bottom-4 fixed z-50 flex flex-col overflow-hidden border shadow-2xl duration-200",
                        "inset-0 sm:inset-auto sm:right-5 sm:bottom-20 sm:rounded-2xl",
                        expanded
                            ? "sm:h-[calc(100svh-7rem)] sm:w-[min(760px,calc(100vw-2.5rem))]"
                            : "sm:h-[min(680px,calc(100svh-7rem))] sm:w-[400px]"
                    )}
                >
                    {/* Header */}
                    <header className="bg-gradient-primary flex items-center gap-3 px-4 py-3 text-white">
                        <AssistantAvatar className="ring-white/40" />
                        <div className="flex min-w-0 flex-1 flex-col">
                            <strong className="truncate text-sm">{t("assistant.name")}</strong>
                            <span className="flex items-center gap-1.5 truncate text-xs text-white/80">
                                <span className="size-1.5 rounded-full bg-emerald-400" />
                                {t("assistant.status")}
                            </span>
                        </div>
                        <HeaderButton
                            label={t(view === "guide" ? "assistant.backToChat" : "assistant.guide")}
                            active={view === "guide"}
                            onClick={() => setView(view === "guide" ? "chat" : "guide")}
                        >
                            <BookOpen />
                        </HeaderButton>
                        <HeaderButton label={t("assistant.newChat")} onClick={reset} disabled={!bubbles.length || busy}>
                            <RotateCcw />
                        </HeaderButton>
                        <HeaderButton
                            label={t(expanded ? "assistant.shrink" : "assistant.expand")}
                            onClick={() => setExpanded((e) => !e)}
                            className="max-sm:hidden"
                        >
                            {expanded ? <Minimize2 /> : <Maximize2 />}
                        </HeaderButton>
                        <HeaderButton label={t("assistant.close")} onClick={() => setOpen(false)}>
                            <X />
                        </HeaderButton>
                    </header>

                    {view === "guide" ? (
                        <AssistantGuide prompts={prompts} onTry={runPrompt} onStart={() => setView("chat")} />
                    ) : (
                        <>
                            {/* Messages */}
                            <div
                                className="bg-muted/40 flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
                                aria-live="polite"
                            >
                                {bubbles.length === 0 && (
                                    <Welcome
                                        name={customer.first_name}
                                        prompts={prompts}
                                        onPrompt={runPrompt}
                                        onGuide={() => setView("guide")}
                                    />
                                )}

                                {bubbles.map((b) => (
                                    <Message key={b.id} bubble={b} />
                                ))}

                                {pending && (
                                    <div className="flex gap-2 ps-11">
                                        <Button onClick={() => decide("approve")}>
                                            <ShieldCheck /> {t("assistant.confirm")}
                                        </Button>
                                        <Button variant="outline" onClick={() => decide("reject")}>
                                            {t("assistant.cancel")}
                                        </Button>
                                    </div>
                                )}

                                {busy && <Typing label={t("assistant.typing")} />}
                                <div ref={bottom} />
                            </div>

                            {/* Suggestions, on demand once the conversation started */}
                            {showChips && bubbles.length > 0 && (
                                <div className="flex gap-2 overflow-x-auto border-t px-3 py-2">
                                    {prompts.map((p) => (
                                        <Chip key={p.key} prompt={p} onClick={() => runPrompt(p)} />
                                    ))}
                                </div>
                            )}

                            {/* Composer */}
                            <form
                                className="bg-background border-t p-3"
                                onSubmit={(e) => {
                                    e.preventDefault();
                                    submit();
                                }}
                            >
                                <div className="focus-within:border-ring focus-within:ring-ring/40 flex items-end gap-1.5 rounded-xl border p-1.5 focus-within:ring-3">
                                    {bubbles.length > 0 && (
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="icon-sm"
                                            aria-label={t("assistant.suggestions")}
                                            aria-pressed={showChips}
                                            className={cn(showChips && "text-primary bg-primary/10")}
                                            onClick={() => setShowChips((s) => !s)}
                                        >
                                            <Lightbulb />
                                        </Button>
                                    )}
                                    <textarea
                                        ref={input}
                                        rows={1}
                                        value={draft}
                                        maxLength={2000}
                                        placeholder={t("assistant.placeholder")}
                                        aria-label={t("assistant.placeholder")}
                                        onChange={(e) => setDraft(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === "Enter" && !e.shiftKey) {
                                                e.preventDefault();
                                                submit();
                                            }
                                        }}
                                        className="placeholder:text-muted-foreground max-h-32 min-h-8 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-sm outline-none"
                                    />
                                    <Button
                                        type="submit"
                                        size="icon-sm"
                                        disabled={busy || !draft.trim()}
                                        aria-label={t("assistant.send")}
                                    >
                                        <SendHorizontal />
                                    </Button>
                                </div>
                                <p className="text-muted-foreground mt-1.5 text-center text-[11px]">
                                    {t("assistant.hintKeys")}
                                </p>
                            </form>
                        </>
                    )}
                </section>
            )}
        </AssistantContext.Provider>
    );
}

function HeaderButton(props: {
    label: string;
    onClick: () => void;
    children: React.ReactNode;
    active?: boolean;
    disabled?: boolean;
    className?: string;
}) {
    return (
        <button
            type="button"
            title={props.label}
            aria-label={props.label}
            aria-pressed={props.active}
            disabled={props.disabled}
            onClick={props.onClick}
            className={cn(
                "inline-flex size-8 items-center justify-center rounded-lg text-white/85 transition hover:bg-white/15 hover:text-white disabled:opacity-40 [&_svg]:size-4",
                props.active && "bg-white/20 text-white",
                props.className
            )}
        >
            {props.children}
        </button>
    );
}

export function Chip({ prompt, onClick }: { prompt: Prompt; onClick: () => void }) {
    const Icon = prompt.icon;
    return (
        <button
            type="button"
            onClick={onClick}
            title={prompt.text}
            className="bg-background hover:border-primary/50 hover:bg-primary/5 inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition"
        >
            <Icon className="text-primary size-3.5" />
            {prompt.label}
        </button>
    );
}

function Welcome(props: {
    name: string | null;
    prompts: Prompt[];
    onPrompt: (p: Prompt) => void;
    onGuide: () => void;
}) {
    const { t } = useTranslation();
    return (
        <div className="flex flex-col items-center gap-4 py-4 text-center">
            <AssistantAvatar className="size-14" />
            <div className="flex flex-col gap-1.5">
                <h2 className="text-lg font-semibold">
                    {props.name ? t("assistant.welcome", { name: props.name }) : t("assistant.welcomeAnon")}
                </h2>
                <p className="text-muted-foreground mx-auto max-w-80 text-sm">{t("assistant.welcomeText")}</p>
                <button
                    type="button"
                    onClick={props.onGuide}
                    className="text-primary bg-primary/10 hover:bg-primary/15 mx-auto mt-1 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition"
                >
                    <BookOpen className="size-3.5" /> {t("assistant.seeGuide")}
                </button>
            </div>

            <div className="flex w-full flex-col gap-2 text-start">
                <span className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                    {t("assistant.tryThis")}
                </span>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {props.prompts.slice(0, 6).map((p) => {
                        const Icon = p.icon;
                        return (
                            <button
                                key={p.key}
                                type="button"
                                onClick={() => props.onPrompt(p)}
                                className="bg-background hover:border-primary/50 hover:bg-primary/5 group flex items-start gap-2.5 rounded-xl border p-3 text-start transition"
                            >
                                <span className="bg-primary/10 text-primary rounded-lg p-1.5">
                                    <Icon className="size-4" />
                                </span>
                                <span className="flex min-w-0 flex-col">
                                    <span className="text-sm font-medium">{p.label}</span>
                                    <span className="text-muted-foreground line-clamp-2 text-xs">{p.text}</span>
                                </span>
                            </button>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}

function Message({ bubble }: { bubble: Bubble }) {
    const { t } = useTranslation();

    if (bubble.from === "user")
        return (
            <div className="bg-primary text-primary-foreground max-w-[85%] self-end rounded-2xl rounded-br-md px-3.5 py-2 text-sm whitespace-pre-wrap shadow-sm">
                {bubble.text}
            </div>
        );

    const confirm = bubble.res?.status === "awaiting_confirmation";
    const handoff = bubble.res?.status === "handed_off" ? bubble.res.handoff : null;

    return (
        <div className="flex max-w-[92%] items-end gap-2 self-start">
            <AssistantAvatar className="size-7 ring-0" />
            <div className="flex min-w-0 flex-col gap-2">
                <div
                    className={cn(
                        "min-w-0 rounded-2xl rounded-bl-md px-3.5 py-2.5 text-sm shadow-sm",
                        bubble.from === "error"
                            ? "bg-destructive/10 text-destructive"
                            : confirm
                              ? "border-primary/30 bg-background border-2"
                              : "bg-background border"
                    )}
                >
                    {confirm && (
                        <span className="text-primary mb-1.5 flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
                            <ShieldCheck className="size-4" /> {t("assistant.confirmTitle")}
                        </span>
                    )}
                    <Rich text={bubble.text} />
                    {confirm && (
                        <span className="text-muted-foreground mt-2 block text-xs">{t("assistant.confirmNote")}</span>
                    )}
                </div>
                {bubble.res?.files?.map((file) => (
                    <FileCard key={file.file_id} file={file} />
                ))}
                {handoff && (
                    <div className="flex items-center gap-2.5 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                        <Headset className="size-4 shrink-0" />
                        <span>
                            <strong className="block">{t("assistant.handoffTitle")}</strong>
                            {t("assistant.handoffRef", { id: handoff.handoff_id })}
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
}

/** A file the assistant generated (Excel or CSV): one click downloads it with the session's token. */
function FileCard({ file }: { file: ChatFile }) {
    const { t } = useTranslation();
    const [state, setState] = useState<"idle" | "busy" | "error">("idle");
    const Icon = file.format === "xlsx" ? FileSpreadsheet : FileText;

    const download = async () => {
        setState("busy");
        try {
            await downloadChatFile(file);
            setState("idle");
        } catch {
            setState("error");
        }
    };

    return (
        <div className="flex flex-col gap-1">
            <button
                type="button"
                onClick={download}
                disabled={state === "busy"}
                aria-label={t("assistant.download", { name: file.filename })}
                title={t("assistant.download", { name: file.filename })}
                className="bg-background hover:border-primary/50 hover:bg-primary/5 group flex items-center gap-2.5 rounded-xl border px-3 py-2 text-start shadow-sm transition disabled:opacity-60"
            >
                <span
                    className={cn(
                        "rounded-lg p-1.5",
                        file.format === "xlsx" ? "bg-emerald-50 text-emerald-700" : "bg-primary/10 text-primary"
                    )}
                >
                    <Icon className="size-5" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-medium">{file.filename}</span>
                    <span className="text-muted-foreground text-xs">
                        {file.format.toUpperCase()} · {t("assistant.fileRows", { count: file.rows })} ·{" "}
                        {formatSize(file.size_bytes)}
                    </span>
                </span>
                {state === "busy" ? (
                    <LoaderCircle className="text-muted-foreground size-4 animate-spin" />
                ) : (
                    <Download className="text-muted-foreground group-hover:text-primary size-4" />
                )}
            </button>
            {state === "error" && <span className="text-destructive text-xs">{t("assistant.fileError")}</span>}
        </div>
    );
}

function formatSize(bytes: number) {
    return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
}

/** Agent replies are Markdown (GFM: tables, lists, headings). Raw HTML is not rendered. */
type Tag = keyof React.JSX.IntrinsicElements;
/** A markdown element rendered as `tag` with Tailwind classes (drops react-markdown's `node` prop). */
const md =
    (tag: Tag, className: string, extra?: object) =>
    ({ node: _node, ...props }: ExtraProps & React.HTMLAttributes<HTMLElement>) => {
        const El = tag as React.ElementType;
        return <El className={className} {...extra} {...props} />;
    };

const markdown: Components = {
    p: md("p", "my-1.5 first:mt-0 last:mb-0"),
    h1: md("h3", "mt-3 mb-1.5 text-base font-semibold first:mt-0"),
    h2: md("h3", "mt-3 mb-1.5 text-base font-semibold first:mt-0"),
    h3: md("h4", "mt-3 mb-1 font-semibold first:mt-0"),
    h4: md("h4", "mt-2 mb-1 font-semibold first:mt-0"),
    ul: md("ul", "my-1.5 list-disc space-y-0.5 ps-5"),
    ol: md("ol", "my-1.5 list-decimal space-y-0.5 ps-5"),
    hr: md("hr", "border-border my-2.5"),
    a: md("a", "text-primary underline", { target: "_blank", rel: "noreferrer" }),
    code: md("code", "bg-muted rounded px-1 py-0.5 font-mono text-xs"),
    blockquote: md("blockquote", "text-muted-foreground my-1.5 border-s-2 ps-3"),
    table: ({ node: _node, ...props }) => (
        <div className="my-2 overflow-x-auto rounded-lg border">
            <table className="w-full text-xs" {...props} />
        </div>
    ),
    thead: md("thead", "bg-muted/60"),
    tr: md("tr", "border-b last:border-0"),
    th: md("th", "px-2 py-1.5 text-start font-semibold whitespace-nowrap"),
    td: md("td", "px-2 py-1.5 whitespace-nowrap"),
};

function Rich({ text }: { text: string }) {
    return (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdown}>
            {text}
        </ReactMarkdown>
    );
}

function Typing({ label }: { label: string }) {
    return (
        <div className="flex items-end gap-2 self-start" role="status" aria-label={label}>
            <AssistantAvatar className="size-7 ring-0" />
            <div className="bg-background flex gap-1 rounded-2xl rounded-bl-md border px-3.5 py-3 shadow-sm">
                {[0, 150, 300].map((delay) => (
                    <span
                        key={delay}
                        className="bg-muted-foreground/60 size-1.5 animate-bounce rounded-full"
                        style={{ animationDelay: `${delay}ms` }}
                    />
                ))}
            </div>
        </div>
    );
}
