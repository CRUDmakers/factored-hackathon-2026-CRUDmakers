import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { BookOpen, House, LogOut } from "lucide-react";
import { cn } from "cn";
import { AssistantAvatar, useAssistant } from "@/components/assistant/assistant";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import useSession from "@/contexts/session/use-session";
import useSystem from "@/contexts/system/use-system";
import bankingCsAiApi from "@/services/api/banking-cs-ai.api";

export default function SessionLayout() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const assistant = useAssistant();
    const { customer } = useSession();

    const logout = async () => {
        await bankingCsAiApi.auth.logout();
        navigate("/auth/sign-in");
    };

    const name = [customer.first_name, customer.last_name].filter(Boolean).join(" ") || customer.customer_id;
    const initials = [customer.first_name, customer.last_name].map((n) => n?.[0] ?? "").join("") || "BL";

    const item = "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition";
    const idle = "text-muted-foreground hover:bg-sidebar-accent hover:text-foreground";

    return (
        <div className="bg-muted/40 flex h-svh w-svw flex-col lg:flex-row">
            {/* Sidebar (desktop) */}
            <aside className="bg-sidebar border-sidebar-border hidden h-full w-64 shrink-0 flex-col gap-6 border-e p-4 lg:flex">
                <Brand />

                <nav className="flex flex-col gap-1" aria-label="Menu">
                    <NavLink
                        to="/session/home"
                        className={({ isActive }) => cn(item, isActive ? "bg-primary/10 text-primary" : idle)}
                    >
                        <House className="size-4" /> {t("nav.home")}
                    </NavLink>
                    <button type="button" className={cn(item, idle)} onClick={() => assistant.open()}>
                        <AssistantAvatar className="size-4 ring-0 [&_svg]:size-2.5" /> {t("nav.assistant")}
                    </button>
                    <button type="button" className={cn(item, idle)} onClick={() => assistant.open({ view: "guide" })}>
                        <BookOpen className="size-4" /> {t("nav.guide")}
                    </button>
                </nav>

                <div className="mt-auto flex flex-col gap-3">
                    <LanguageSwitch />
                    <div className="bg-background flex items-center gap-3 rounded-xl border p-3">
                        <span className="bg-primary/10 text-primary flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold">
                            {initials}
                        </span>
                        <div className="flex min-w-0 flex-col">
                            <strong className="truncate text-sm">{name}</strong>
                            <span className="text-muted-foreground truncate text-xs">
                                {[customer.segment, customer.country].filter(Boolean).join(" · ")}
                            </span>
                        </div>
                    </div>
                    <button type="button" onClick={logout} className={cn(item, idle)}>
                        <LogOut className="size-4" /> {t("logout")}
                    </button>
                </div>
            </aside>

            {/* Top bar (mobile) */}
            <header className="bg-sidebar flex items-center gap-3 border-b px-4 py-3 lg:hidden">
                <Brand />
                <div className="ms-auto flex items-center gap-2">
                    <LanguageSwitch />
                    <button
                        type="button"
                        onClick={logout}
                        aria-label={t("logout")}
                        className="text-muted-foreground hover:bg-sidebar-accent rounded-lg p-2"
                    >
                        <LogOut className="size-4" />
                    </button>
                </div>
            </header>

            <main className="min-h-0 flex-1 overflow-y-auto">
                <Outlet />
            </main>
        </div>
    );
}

function Brand() {
    return (
        <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="size-9 rounded-lg" />
            <div className="flex flex-col leading-tight">
                <strong className="text-sm">Banco LATAM</strong>
                <span className="text-muted-foreground text-[11px] max-sm:hidden">México · Colombia · Argentina</span>
            </div>
        </div>
    );
}

function LanguageSwitch() {
    const { t } = useTranslation();
    const { language, setLanguage } = useSystem();
    return (
        <ToggleGroup
            aria-label={t("nav.language")}
            multiple={false}
            value={[language]}
            onValueChange={(v) => setLanguage(v[0])}
            className="w-fit"
        >
            <ToggleGroupItem value="pt">PT</ToggleGroupItem>
            <ToggleGroupItem value="es">ES</ToggleGroupItem>
        </ToggleGroup>
    );
}
