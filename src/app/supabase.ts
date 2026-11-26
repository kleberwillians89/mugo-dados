import { AuthClient } from "@supabase/auth-js";
import { PostgrestClient } from "@supabase/postgrest-js";

const url = String(import.meta.env.VITE_SUPABASE_URL || "").trim();
const anon = String(import.meta.env.VITE_SUPABASE_ANON_KEY || "").trim();
const LOCAL_AUTH_STORAGE_KEY = "mugo_dados.local_auth";
export const SUPABASE_AUTH_OPTIONS = {
  persistSession: true,
  autoRefreshToken: true,
  detectSessionInUrl: true,
} as const;

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

/**
 * Cliente enxuto: só o login (auth) e as consultas (rest), que é tudo o que o app usa. Antes era o
 * supabase-js inteiro (realtime, storage, functions…), ~200 KB baixados em toda tela, inclusive pelo
 * celular do cliente na aprovação. Mesma chave de sessão do supabase-js: ninguém é deslogado.
 */
export type SlimSupabaseClient = {
  auth: InstanceType<typeof AuthClient>;
  from: (relation: string) => ReturnType<PostgrestClient["from"]>;
};

/** Mesma chave que o supabase-js usava (sb-<projeto>-auth-token): quem já está logado continua logado. */
export function authStorageKey(supabaseUrl: string): string {
  return `sb-${new URL(supabaseUrl).hostname.split(".")[0]}-auth-token`;
}

export function createSlimClient(supabaseUrl: string, key: string): SlimSupabaseClient {
  const base = supabaseUrl.replace(/\/+$/, "");
  const headers = { "X-Client-Info": "mugo-dados-web" };
  const auth = new AuthClient({
    url: `${base}/auth/v1`,
    headers: { ...headers, Authorization: `Bearer ${key}`, apikey: key },
    storageKey: authStorageKey(base),
    flowType: "implicit",
    ...SUPABASE_AUTH_OPTIONS,
  });
  // Igual ao supabase-js: cada consulta vai com o token da sessão (ou a chave pública, sem sessão).
  const fetchWithAuth: typeof fetch = async (input, init) => {
    const { data } = await auth.getSession();
    const merged = new Headers(init?.headers);
    if (!merged.has("apikey")) merged.set("apikey", key);
    if (!merged.has("Authorization")) merged.set("Authorization", `Bearer ${data.session?.access_token ?? key}`);
    return fetch(input, { ...init, headers: merged });
  };
  const rest = new PostgrestClient(`${base}/rest/v1`, { headers, fetch: fetchWithAuth });
  return { auth, from: (relation: string) => rest.from(relation) };
}

let supabaseClient: SlimSupabaseClient | null = null;
let supabaseBootstrapError: string | null = buildBootstrapError();

if (!supabaseBootstrapError) {
  try {
    supabaseClient = createSlimClient(url, anon);
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
