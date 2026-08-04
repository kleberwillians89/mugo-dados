const ACTIVE_CONNECTION_KEY = "mugo_dados.active_connection_id";
const SELECTED_CONNECTIONS_KEY = "mugo_dados.selected_connections";

export function getActiveConnectionId(): string | null {
  try {
    const raw = localStorage.getItem(ACTIVE_CONNECTION_KEY);
    return raw && raw.trim() ? raw.trim() : null;
  } catch {
    return null;
  }
}

export function setActiveConnectionId(connectionId: string | null | undefined): void {
  try {
    const nextConnectionId = String(connectionId || "").trim();
    if (!nextConnectionId) {
      localStorage.removeItem(ACTIVE_CONNECTION_KEY);
      return;
    }
    localStorage.setItem(ACTIVE_CONNECTION_KEY, nextConnectionId);
  } catch {
    // no-op
  }
}

export function getSelectedConnectionId(clientId: string, provider: string): string | null {
  try {
    const stored = JSON.parse(window.localStorage.getItem(SELECTED_CONNECTIONS_KEY) || "{}");
    const value = stored?.[String(clientId || "").trim()]?.[String(provider || "").trim()];
    return String(value || "").trim() || null;
  } catch {
    return null;
  }
}

export function setSelectedConnectionId(clientId: string, provider: string, connectionId: string | null): void {
  const cid = String(clientId || "").trim();
  const product = String(provider || "").trim();
  if (!cid || !product) return;
  let stored: Record<string, Record<string, string>> = {};
  try {
    stored = JSON.parse(window.localStorage.getItem(SELECTED_CONNECTIONS_KEY) || "{}");
  } catch {
    stored = {};
  }
  const tenant = { ...(stored[cid] || {}) };
  if (connectionId) tenant[product] = String(connectionId).trim();
  else delete tenant[product];
  stored[cid] = tenant;
  window.localStorage.setItem(SELECTED_CONNECTIONS_KEY, JSON.stringify(stored));
}
