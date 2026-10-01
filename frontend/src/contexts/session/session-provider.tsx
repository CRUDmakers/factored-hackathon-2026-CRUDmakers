import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";
import { api, setSessionLostHandler } from "@/api";
import { AssistantProvider } from "@/components/assistant/assistant";
import { Button } from "@/components/ui/button";
import useSystem from "@/contexts/system/use-system";
import { useAsync } from "@/hooks/useAsync";
import bankingCsAiApi from "@/services/api/banking-cs-ai.api";
import { SessionContext } from "./use-session";

export default function SessionProvider({ children }: { children: React.ReactNode }) {
    const navigate = useNavigate();
    const { showAlert } = useSystem();
    const { t } = useTranslation();
    const { reload: reloadSession, data: session, loading } = useAsync(() => bankingCsAiApi.auth.getSession(), []);

    // Any 401 from either backend (expired, logged out, revoked) lands here.
    useEffect(() => {
        setSessionLostHandler((reason) => {
            showAlert(t(reason === "expired" ? "session.expired" : "session.invalid"), "warning");
            navigate("/auth/sign-in", { replace: true });
        });
        return () => setSessionLostHandler(() => {});
    }, [navigate, showAlert, t]);

    if (loading) return <FullScreenLoading />;
    if (!session) return <Navigate to="/auth/sign-in" replace />;

    return (
        <SessionData session={session} reloadSession={reloadSession}>
            {children}
        </SessionData>
    );
}

function SessionData(props: { session: { customerId: string }; reloadSession: () => void; children: React.ReactNode }) {
    const { t } = useTranslation();
    const customer = useAsync(() => api.customer(), [props.session.customerId]);
    const balances = useAsync(() => api.balances(), [props.session.customerId]);

    if (customer.error || balances.error)
        return (
            <FullScreenLoading>
                <Button
                    onClick={() => {
                        customer.reload();
                        balances.reload();
                    }}
                >
                    {t("retry")}
                </Button>
            </FullScreenLoading>
        );
    if (!customer.data || !balances.data) return <FullScreenLoading />;

    return (
        <SessionContext.Provider
            value={{
                session: props.session,
                reloadSession: props.reloadSession,
                customer: customer.data,
                balances: balances.data,
                reloadBalances: balances.reload,
            }}
        >
            <AssistantProvider>{props.children}</AssistantProvider>
        </SessionContext.Provider>
    );
}

function FullScreenLoading({ children }: { children?: React.ReactNode }) {
    const { t } = useTranslation();
    return (
        <div className="bg-background text-muted-foreground flex h-svh w-svw flex-col items-center justify-center gap-4">
            {children ?? (
                <>
                    <span className="border-primary size-8 animate-spin rounded-full border-2 border-t-transparent" />
                    <span className="text-sm">{t("loading")}</span>
                </>
            )}
        </div>
    );
}
