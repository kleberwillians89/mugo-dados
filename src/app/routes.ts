export type AppRoute =
  | "meta"
  | "google"
  | "ecommerce"
  | "customers"
  | "goals"
  | "calendar"
  | "library"
  | "integrations"
  | "origins"
  | "intelligence"
  | "companies"
  | "not_found";

export type PublicAppRoute = "privacy" | "data_deletion" | "data_protection" | "terms";

export function getPublicAppRouteFromPath(pathname: string): PublicAppRoute | null {
  const normalized = String(pathname || "/").trim().toLowerCase().replace(/\/+$/, "") || "/";
  if (normalized === "/privacidade") return "privacy";
  if (normalized === "/exclusao-de-dados") return "data_deletion";
  if (normalized === "/protecao-de-dados") return "data_protection";
  if (normalized === "/termos-de-uso" || normalized === "/termos") return "terms";
  return null;
}

export function getAppRouteFromPath(pathname: string): AppRoute {
  const normalized = String(pathname || "/").trim().toLowerCase();
  if (normalized.startsWith("/empresas")) return "companies";
  if (normalized === "/metas" || normalized.startsWith("/metas/")) return "goals";
  if (normalized === "/calendario" || normalized.startsWith("/calendario/")) return "calendar";
  if (normalized === "/biblioteca" || normalized.startsWith("/biblioteca/")) return "library";
  if (normalized.startsWith("/meta")) return "meta";
  if (
    normalized === "/" ||
    normalized === "" ||
    normalized.startsWith("/dashboard") ||
    normalized.startsWith("/overview") ||
    normalized.startsWith("/visao-geral")
  ) return "meta";
  if (normalized.startsWith("/integracoes")) return "integrations";
  if (normalized.startsWith("/origem-das-vendas")) return "origins";
  if (normalized.startsWith("/inteligencia")) return "intelligence";
  if (normalized.startsWith("/ecommerce")) return "ecommerce";
  if (normalized.startsWith("/clientes")) return "customers";
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
  if (route === "origins") return "/origem-das-vendas";
  if (route === "intelligence") return "/inteligencia";
  if (route === "google") return "/google";
  if (route === "ecommerce") return "/ecommerce";
  if (route === "goals") return "/metas";
  if (route === "calendar") return "/calendario";
  if (route === "library") return "/biblioteca";
  if (route === "customers") return "/clientes";
  if (route === "not_found") return "/404";
  return "/meta";
}

export function navigateToAppRoute(route: AppRoute, options?: { replace?: boolean }) {
  const path = getPathForRoute(route);
  const method = options?.replace ? "replaceState" : "pushState";
  window.history[method]({}, document.title, path);
}
