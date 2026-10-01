import { createContext, useContext } from "react";
import type { Balances, Customer } from "@/api";

type SessionContextProps = {
    session: { customerId: string };
    reloadSession: () => void;
    customer: Customer;
    balances: Balances;
    /** Called after the assistant completes a payment, so every screen shows the new balances. */
    reloadBalances: () => void;
};

export const SessionContext = createContext<SessionContextProps>(null!);

export default function useSession() {
    const context = useContext(SessionContext);
    if (!context) throw new Error("useSession must be used within a SessionProvider");

    return context;
}
