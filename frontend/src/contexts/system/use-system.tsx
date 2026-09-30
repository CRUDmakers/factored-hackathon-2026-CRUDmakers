import { createContext, useContext } from "react";

type SystemContextProps = {
    language: string;
    setLanguage: (language: string) => void;

    showAlert: (message: string, type?: "success" | "warning" | "error") => void;
};

export const SystemContext = createContext<SystemContextProps>(null!);

export default function useSystem() {
    const context = useContext(SystemContext);
    if (!context) throw new Error("useSystem must be used within a SystemProvider");

    return context;
}
