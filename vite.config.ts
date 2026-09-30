import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { LEGAL_CONTACT, LEGAL_CONTACT_PLACEHOLDER } from "./src/app/legalContact";

// Proteção: as páginas públicas exigidas pela Meta nunca vão para produção
// com o contato placeholder. Só o build de produção da Vercel é bloqueado;
// build local e previews seguem funcionando.
if (process.env.VERCEL_ENV === "production" && LEGAL_CONTACT === LEGAL_CONTACT_PLACEHOLDER) {
  throw new Error(
    `LEGAL_CONTACT ainda é ${LEGAL_CONTACT_PLACEHOLDER}. Defina o canal oficial em src/app/legalContact.ts antes do deploy de produção.`
  );
}

export default defineConfig({
  define: {
    __APP_COMMIT_SHA__: JSON.stringify(
      process.env.VITE_GIT_COMMIT_SHA || process.env.VERCEL_GIT_COMMIT_SHA || process.env.GIT_COMMIT_SHA || "unknown"
    ),
    __APP_BUILD_TIME__: JSON.stringify(process.env.VITE_BUILD_TIME || new Date().toISOString()),
  },
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist",
    sourcemap: false,
    minify: "terser",
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
