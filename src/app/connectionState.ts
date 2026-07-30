const ACTIVE_CONNECTION_KEY = "mugo_dados.active_connection_id";

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
