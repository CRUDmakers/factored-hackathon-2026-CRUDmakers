import { createContext, useContext } from "react";

type SessionContextProps = { session: { customerId: string }; reloadSession: () => void };

export const SessionContext = createContext<SessionContextProps>(null!);

export default function useSession() {
    const context = useContext(SessionContext);
    if (!context) throw new Error("useSession must be used within a SessionProvider");

    return context;
}
