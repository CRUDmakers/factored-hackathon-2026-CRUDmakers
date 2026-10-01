import LanguageDetector from "i18next-browser-languagedetector";
import i18next from "i18next";

import { initReactI18next } from "react-i18next";

import ptAuth from "./pt/auth.json";
import ptCommon from "./pt/common.json";
import ptValidation from "./pt/validation.json";

import esAuth from "./es/auth.json";
import esCommon from "./es/common.json";
import esValidation from "./es/validation.json";

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
        // React already escapes rendered text; i18next's HTML escaping turned "01/04" into "01&#x2F;04".
        interpolation: { escapeValue: false },

        ns: [...namespaces],
        defaultNS,

        resources: {
            pt: { auth: ptAuth, common: ptCommon, validation: ptValidation },
            es: { auth: esAuth, common: esCommon, validation: esValidation },
        },

        detection: {
            order: ["localStorage"],
            caches: ["localStorage"],
            lookupLocalStorage: "i18nextLng",
        },
    });
