export type ConnectionRecord = {
  id?: string | null;
  client_id?: string | null;
  provider?: string | null;
  platform?: string | null;
  connection_type?: string | null;
  status?: string | null;
  disconnected_at?: string | null;
  token_available?: boolean;
  metadata?: Record<string, unknown> | null;
};

export function selectUniqueConnection<T>(items: T[], predicate: (item: T) => boolean): T | null {
  const matches = items.filter(predicate);
  if (matches.length !== 1) return null;
  const [match] = matches;
  return match;
}

export function resolveCatalogConnection<T extends ConnectionRecord>(
  connections: T[], input: {
    clientId: string; provider: string; requestedConnectionId?: string | null;
    requireToken?: boolean; allowedStatuses?: string[];
  }
): T | null {
  const statuses = input.allowedStatuses || ["connected", "selection_required"];
  const candidates = connections.filter((connection) =>
    connection.client_id === input.clientId &&
    connection.provider === input.provider &&
    statuses.includes(String(connection.status || "").toLowerCase()) &&
    !connection.disconnected_at &&
    (input.requireToken === false || connection.token_available !== false)
  );
  const requested = String(input.requestedConnectionId || "").trim();
  if (!requested) return null;
  const exact = candidates.filter((connection) => connection.id === requested);
  if (exact.length !== 1) return null;
  const [match] = exact;
  return match;
}

export function resolveOperationalMetaConnectionId(
  connections: ConnectionRecord[],
  capability: "organic" | "paid",
  requestedConnectionId?: string | null,
): string | null {
  const requested = String(requestedConnectionId || "").trim();
  const candidates = connections.filter((connection) => {
    const platform = String(connection.platform || "").toLowerCase();
    const kind = String(connection.connection_type || "").toLowerCase();
    const status = String(connection.status || "").toLowerCase();
    const capabilityMatches = capability === "organic"
      ? platform === "instagram" || kind === "organic"
      : platform === "meta_ads" || kind === "paid";
    return capabilityMatches && status !== "disconnected" && !connection.disconnected_at;
  });
  if (!requested) return null;
  const exact = candidates.filter((connection) => connection.id === requested);
  if (exact.length !== 1) return null;
  const [match] = exact;
  return String(match.id || "") || null;
}

export function resolveCommerceConnection<T extends ConnectionRecord>(
  connections: T[], requestedConnectionId?: string | null
): T | null {
  const candidates = connections.filter((connection) =>
    ["shopify", "fbits"].includes(String(connection.provider || "").toLowerCase()) &&
    ["connected", "active", "updated"].includes(String(connection.status || "").toLowerCase()) &&
    !connection.disconnected_at
  );
  const requested = String(requestedConnectionId || "").trim();
  if (!requested) return null;
  const exact = candidates.filter((connection) => connection.id === requested);
  if (exact.length !== 1) return null;
  const [match] = exact;
  return match;
}
