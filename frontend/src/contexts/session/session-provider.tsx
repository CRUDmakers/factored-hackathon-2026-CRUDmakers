import { useAsync } from "@/hooks/useAsync";
import { SessionContext } from "./use-session";
import bankingCsAiApi from "@/services/api/banking-cs-ai.api";

export default function SessionProvider({ children }: { children: React.ReactNode }) {
    const { reload: reloadSession, data: session } = useAsync(() => bankingCsAiApi.auth.getSession(), []);

    if (!session) return <div>Loading session ...</div>;

    return <SessionContext.Provider value={{ session, reloadSession }}>{children}</SessionContext.Provider>;
}
