import { toast, Toaster } from "@/components/ui/toast";
import { SystemContext } from "./use-system";
import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

export default function SystemProvider({ children }: { children: React.ReactNode }) {
    const { i18n } = useTranslation();
    const language = i18n.resolvedLanguage === "es" ? "es" : "pt";

    const setLanguage = useCallback((language: string) => void (language && i18n.changeLanguage(language)), [i18n]);

    useEffect(() => {
        document.documentElement.lang = language;
    }, [language]);

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
