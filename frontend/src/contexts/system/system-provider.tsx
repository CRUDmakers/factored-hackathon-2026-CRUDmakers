import { toast, Toaster } from "@/components/ui/toast";
import { SystemContext } from "./use-system";
import { useCallback, useState } from "react";

export default function SystemProvider({ children }: { children: React.ReactNode }) {
    const [language, setLanguage] = useState("pt");

    const showAlert = useCallback((message: string, type?: "success" | "warning" | "error") => {
        toast.add({ description: message, type });
    }, []);

    return (
        <SystemContext.Provider value={{ language, setLanguage, showAlert }}>
            {children}
            <Toaster />
        </SystemContext.Provider>
    );
}
