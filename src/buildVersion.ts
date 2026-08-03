declare const __APP_COMMIT_SHA__: string;
declare const __APP_BUILD_TIME__: string;

export const FRONTEND_COMMIT_SHA = String(__APP_COMMIT_SHA__ || "unknown");
export const FRONTEND_BUILD_TIME = String(__APP_BUILD_TIME__ || "unknown");
export const INTEGRATION_BUILD_FEATURES = [
  "manual-assets/validate",
  "manual-assets",
  "GOOGLE_REAUTH_REQUIRED",
  "listGoogleGa4Properties",
  "token_available",
].join(",");

export function shortCommit(value: string): string {
  const normalized = String(value || "").trim();
  return normalized && normalized !== "unknown" ? normalized.slice(0, 7) : "unknown";
}

export function commitsMismatch(frontend: string, backend: string): boolean {
  const left = String(frontend || "").trim();
  const right = String(backend || "").trim();
  return Boolean(left && right && left !== "unknown" && right !== "unknown" && left !== right);
}
