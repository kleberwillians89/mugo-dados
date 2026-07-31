export type ActiveClient = {
  id: string;
  name: string;
  role?: string | null;
};

const ACTIVE_CLIENT_STORAGE_KEY = "mugo_dados.active_client";

function readStoredClient(): ActiveClient | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(ACTIVE_CLIENT_STORAGE_KEY) || "null");
    const id = String(parsed?.id || "").trim();
    const name = String(parsed?.name || "").trim();
    return id ? { id, name: name || "Cliente", role: parsed?.role || null } : null;
  } catch {
    return null;
  }
}

export const MUGO_APP_NAME = "Mugô Dados";
export const MUGO_TAGLINE = "Inteligência de dados para decisões mais claras.";

export function setActiveClient(client: ActiveClient): void {
  const id = String(client.id || "").trim();
  if (!id) throw new Error("Não é possível selecionar um cliente sem ID.");
  localStorage.setItem(
    ACTIVE_CLIENT_STORAGE_KEY,
    JSON.stringify({ id, name: String(client.name || "Cliente"), role: client.role || null })
  );
}

export function clearActiveClient(): void {
  localStorage.removeItem(ACTIVE_CLIENT_STORAGE_KEY);
}

export function clearTenantBrowserState(): void {
  clearActiveClient();
  try {
    window.localStorage.removeItem("mugo_dados.active_connection_id");
    for (let index = window.sessionStorage.length - 1; index >= 0; index -= 1) {
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
