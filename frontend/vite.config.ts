import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig({
    plugins: [react(), tailwindcss(), tsconfigPaths()],
    server: { port: 5173 },
    preview: { port: 5173 },
});
