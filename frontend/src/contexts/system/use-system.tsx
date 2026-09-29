import { createContext, useContext } from "react";

type SystemContextProps = {
    language: string;
    setLanguage: (language: string) => void;
};

export const SystemContext = createContext<SystemContextProps>(null!);

export default function useSystem() {
    return useContext(SystemContext);
}
