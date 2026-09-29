import { SystemContext } from "./use-system";
import { useState } from "react";

export default function SystemProvider({ children }: { children: React.ReactNode }) {
    const [language, setLanguage] = useState("pt");

    return <SystemContext.Provider value={{ language, setLanguage }}>{children}</SystemContext.Provider>;
}
