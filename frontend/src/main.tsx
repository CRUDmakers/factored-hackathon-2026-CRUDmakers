import "./locales/i18n.ts";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import SystemProvider from "./contexts/system/system-provider";
import AppRouter from "./app-router";

import "./styles.css";

const root = document.getElementById("root");

if (!root) {
    throw new Error("Root element not found");
}

createRoot(root).render(
    <StrictMode>
        <SystemProvider>
            <AppRouter />
        </SystemProvider>
    </StrictMode>
);
