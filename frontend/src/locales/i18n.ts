import LanguageDetector from "i18next-browser-languagedetector";
import i18next from "i18next";

import { initReactI18next } from "react-i18next";

import ptAuth from "./pt/auth.json";
import ptCommon from "./pt/common.json";
import esAuth from "./es/auth.json";
import esCommon from "./es/common.json";

export const i18nLangs: { value: "pt" | "es"; flag: string }[] = [
    { value: "pt", flag: "🇧🇷" },
    { value: "es", flag: "🇪🇸" },
];

export const defaultNS = "common";
const namespaces = ["auth", "common"];

i18next
    .use(initReactI18next)
    .use(LanguageDetector)
    .init({
        react: { useSuspense: true },
        debug: import.meta.env.VITE_ENV === "development",

        fallbackLng: "pt",

        ns: [...namespaces],
        defaultNS,

        resources: {
            pt: { auth: ptAuth, common: ptCommon },
            es: { auth: esAuth, common: esCommon },
        },

        detection: {
            order: ["localStorage"],
            caches: ["localStorage"],
            lookupLocalStorage: "i18nextLng",
        },
    });
