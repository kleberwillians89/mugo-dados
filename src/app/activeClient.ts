import { clearDashboardCacheByPrefix } from "../hooks/dashboard/cache";
export type ActiveClient = {
  id: string;
  name: string;
  role?: string | null;
};

const ACTIVE_CLIENT_STORAGE_KEY = "mugo_dados.active_client";
const LEGACY_CLIENT_ALIASES: Record<string, string> = {
  "9cd90217-ccba-4467-a095-eedc21fe6e86": "amalie",
};

export function canonicalizeClientId(value: string | null | undefined): string {
  const id = String(value || "").trim();
  return LEGACY_CLIENT_ALIASES[id] || id;
}

function readStoredClient(): ActiveClient | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(ACTIVE_CLIENT_STORAGE_KEY) || "null");
    const id = canonicalizeClientId(parsed?.id);
    const name = String(parsed?.name || "").trim();
    return id ? { id, name: name || "Cliente", role: parsed?.role || null } : null;
  } catch {
    return null;
  }
}

export const MUGO_APP_NAME = "Mugô Dados";
export const MUGO_TAGLINE = "Inteligência de dados para decisões mais claras.";

export function setActiveClient(client: ActiveClient): void {
  const id = canonicalizeClientId(client.id);
  if (!id) throw new Error("Não é possível selecionar um cliente sem ID.");
  localStorage.setItem(
    ACTIVE_CLIENT_STORAGE_KEY,
    JSON.stringify({ id, name: String(client.name || "Cliente"), role: client.role || null })
  );
}

export function clearActiveClient(): void {
  localStorage.removeItem(ACTIVE_CLIENT_STORAGE_KEY);
}

export function clearTenantBrowserState(options?: { preserveCaches?: boolean }): void {
  clearActiveClient();
  try {
    window.localStorage.removeItem("mugo_dados.active_connection_id");
    if (!options?.preserveCaches) clearDashboardCacheByPrefix("");
    for (let index = options?.preserveCaches ? -1 : window.sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = window.sessionStorage.key(index);
      if (key?.startsWith("client-dashboard-cache:")) {
        window.sessionStorage.removeItem(key);
      }
    }
  } catch {
    // Browser storage can be unavailable in restricted contexts.
  }
}

export function getActiveClient(): ActiveClient | null {
  return readStoredClient();
}

export function getActiveClientName(): string {
  return readStoredClient()?.name || "Cliente";
}

export function getActiveClientConfigurationWarning(): string | null {
  return getActiveClientId()
    ? null
    : "Selecione uma empresa vinculada à sua conta para carregar os dados.";
}

export function getActiveClientId(): string {
  return readStoredClient()?.id || "";
}
