export type AppRoute =
  | "meta"
  | "google"
  | "ecommerce"
  | "integrations"
  | "intelligence"
  | "companies"
  | "not_found";

export type PublicAppRoute = "privacy" | "data_deletion";

export function getPublicAppRouteFromPath(pathname: string): PublicAppRoute | null {
  const normalized = String(pathname || "/").trim().toLowerCase().replace(/\/+$/, "") || "/";
  if (normalized === "/privacidade") return "privacy";
  if (normalized === "/exclusao-de-dados") return "data_deletion";
  return null;
}

export function getAppRouteFromPath(pathname: string): AppRoute {
  const normalized = String(pathname || "/").trim().toLowerCase();
  if (normalized.startsWith("/empresas")) return "companies";
  if (normalized.startsWith("/meta")) return "meta";
  if (
    normalized === "/" ||
    normalized === "" ||
    normalized.startsWith("/dashboard") ||
    normalized.startsWith("/overview") ||
    normalized.startsWith("/visao-geral")
  ) return "meta";
  if (normalized.startsWith("/integracoes")) return "integrations";
  if (normalized.startsWith("/inteligencia")) return "intelligence";
  if (normalized.startsWith("/ecommerce")) return "ecommerce";
  if (normalized.startsWith("/google") || normalized.startsWith("/analytics")) return "google";
  return "not_found";
}

export function getCurrentAppRoute(): AppRoute {
  return getAppRouteFromPath(window.location.pathname);
}

export function getPathForRoute(route: AppRoute): string {
  if (route === "companies") return "/empresas";
  if (route === "meta") return "/meta";
  if (route === "integrations") return "/integracoes";
  if (route === "intelligence") return "/inteligencia";
  if (route === "google") return "/google";
  if (route === "ecommerce") return "/ecommerce";
  if (route === "not_found") return "/404";
  return "/meta";
}

export function navigateToAppRoute(route: AppRoute, options?: { replace?: boolean }) {
  const path = getPathForRoute(route);
  const method = options?.replace ? "replaceState" : "pushState";
  window.history[method]({}, document.title, path);
}
