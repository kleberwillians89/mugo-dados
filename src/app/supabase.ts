import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = String(import.meta.env.VITE_SUPABASE_URL || "").trim();
const anon = String(import.meta.env.VITE_SUPABASE_ANON_KEY || "").trim();
const LOCAL_AUTH_STORAGE_KEY = "mugo_dados.local_auth";

function buildBootstrapError(): string | null {
  const missing: string[] = [];
  if (!url) missing.push("VITE_SUPABASE_URL");
  if (!anon) missing.push("VITE_SUPABASE_ANON_KEY");
  if (!missing.length) return null;
  return [
    `Configuracao ausente no frontend: ${missing.join(", ")}.`,
    "Defina as variaveis Vite do Supabase para liberar login e sessao do cliente ativo.",
  ].join(" ");
}

let supabaseClient: SupabaseClient | null = null;
let supabaseBootstrapError: string | null = buildBootstrapError();

if (!supabaseBootstrapError) {
  try {
    supabaseClient = createClient(url, anon, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  } catch (error: unknown) {
    const detail =
      error instanceof Error && error.message
        ? error.message
        : "Falha ao inicializar o cliente do Supabase.";
    supabaseBootstrapError = `${detail} Revise VITE_SUPABASE_URL e VITE_SUPABASE_ANON_KEY.`;
  }
}

export const supabase = supabaseClient;

export function getSupabaseBootstrapError(): string | null {
  return supabaseBootstrapError;
}

export function isLocalAuthAvailable(): boolean {
  return import.meta.env.DEV && String(import.meta.env.VITE_ALLOW_LOCAL_AUTH || "").trim() === "true";
}

export function isLocalAuthEnabled(): boolean {
  if (!isLocalAuthAvailable()) return false;
  try {
    return window.localStorage.getItem(LOCAL_AUTH_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function enableLocalAuth(): void {
  if (!isLocalAuthAvailable()) return;
  try {
    window.localStorage.setItem(LOCAL_AUTH_STORAGE_KEY, "1");
    window.dispatchEvent(new Event("client-local-auth-change"));
  } catch {
    // no-op
  }
}

export function disableLocalAuth(): void {
  try {
    window.localStorage.removeItem(LOCAL_AUTH_STORAGE_KEY);
    window.dispatchEvent(new Event("client-local-auth-change"));
  } catch {
    // no-op
  }
}
