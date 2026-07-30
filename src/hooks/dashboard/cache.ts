type CacheEntry<T> = {
  value: T;
  expiresAt: number;
};

const DASH_CACHE = new Map<string, CacheEntry<unknown>>();
const DASH_CACHE_PREFIX = "client-dashboard-cache:";

function storageKey(key: string): string {
  return `${DASH_CACHE_PREFIX}${key}`;
}

function readStoredEntry<T>(key: string): CacheEntry<T> | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(key));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEntry<T>;
    if (!parsed || typeof parsed.expiresAt !== "number") return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeStoredEntry<T>(key: string, entry: CacheEntry<T>): void {
  try {
    window.sessionStorage.setItem(storageKey(key), JSON.stringify(entry));
  } catch {
    // The in-memory cache remains available when storage is blocked or full.
  }
}

function deleteStoredEntry(key: string): void {
  try {
    window.sessionStorage.removeItem(storageKey(key));
  } catch {
    // no-op
  }
}

export function buildDashboardCacheKey(
  scope: string,
  input: {
    clientId: string;
    connectionId?: string | null;
    start?: string;
    end?: string;
    extra?: string;
  }
): string {
  const client = String(input.clientId || "").trim() || "-";
  const connection = String(input.connectionId || "").trim() || "-";
  const start = String(input.start || "").trim() || "-";
  const end = String(input.end || "").trim() || "-";
  const extra = String(input.extra || "").trim() || "-";
  return `${scope}|c=${client}|k=${connection}|s=${start}|e=${end}|x=${extra}`;
}

export function readDashboardCache<T>(key: string): T | null {
  const entry = (DASH_CACHE.get(key) as CacheEntry<T> | undefined) || readStoredEntry<T>(key);
  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    DASH_CACHE.delete(key);
    deleteStoredEntry(key);
    return null;
  }
  DASH_CACHE.set(key, entry as CacheEntry<unknown>);
  return entry.value as T;
}

export function writeDashboardCache<T>(key: string, value: T, ttlMs = 180_000): void {
  const safeTtl = Math.max(900_000, Math.floor(ttlMs || 180_000));
  const entry = {
    value,
    expiresAt: Date.now() + safeTtl,
  };
  DASH_CACHE.set(key, entry);
  writeStoredEntry(key, entry);
}

export function clearDashboardCacheByPrefix(prefix: string): void {
  for (const key of DASH_CACHE.keys()) {
    if (key.startsWith(prefix)) {
      DASH_CACHE.delete(key);
      deleteStoredEntry(key);
    }
  }
  try {
    for (let index = window.sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = window.sessionStorage.key(index);
      if (!key?.startsWith(DASH_CACHE_PREFIX)) continue;
      const dashboardKey = key.slice(DASH_CACHE_PREFIX.length);
      if (dashboardKey.startsWith(prefix)) window.sessionStorage.removeItem(key);
    }
  } catch {
    // no-op
  }
}
