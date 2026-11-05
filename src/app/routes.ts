export type AppRoute =
  | "meta"
  | "google"
  | "ecommerce"
  | "customers"
  | "goals"
  | "calendar"
  | "approval"
  | "media"
  | "tasks"
  | "central"
  | "clipping"
  | "engagement"
  | "social_report"
  | "campaigns"
  | "creators"
  | "automations"
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
  // Aprovação mora no Calendário (visão Fluxo); o endereço antigo abre o Calendário já no Fluxo.
  if (normalized === "/aprovacao" || normalized.startsWith("/aprovacao/")) return "calendar";
  if (normalized === "/midia" || normalized.startsWith("/midia/")) return "media";
  if (normalized === "/tarefas" || normalized.startsWith("/tarefas/")) return "tasks";
  if (normalized === "/central" || normalized.startsWith("/central/")) return "central";
  if (normalized === "/clipping" || normalized.startsWith("/clipping/")) return "clipping";
  if (normalized === "/comentarios" || normalized.startsWith("/comentarios/")) return "engagement";
  if (normalized === "/relatorio-social" || normalized.startsWith("/relatorio-social/")) return "social_report";
  if (normalized === "/redacao" || normalized.startsWith("/redacao/")) return "campaigns";
  if (normalized === "/criadores" || normalized.startsWith("/criadores/")) return "creators";
  if (normalized === "/automacoes" || normalized.startsWith("/automacoes/")) return "automations";
  // Atendimento mora no painel Cliente do Calendário; o endereço antigo continua funcionando.
  if (normalized === "/atendimento" || normalized.startsWith("/atendimento/")) return "calendar";
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
  if (route === "approval") return "/calendario";
  if (route === "media") return "/midia";
  if (route === "tasks") return "/tarefas";
  if (route === "central") return "/central";
  if (route === "clipping") return "/clipping";
  if (route === "engagement") return "/comentarios";
  if (route === "social_report") return "/relatorio-social";
  if (route === "campaigns") return "/redacao";
  if (route === "creators") return "/criadores";
  if (route === "automations") return "/automacoes";
  if (route === "customers") return "/clientes";
  if (route === "not_found") return "/404";
  return "/meta";
}

export function navigateToAppRoute(route: AppRoute, options?: { replace?: boolean }) {
  const path = getPathForRoute(route);
  const method = options?.replace ? "replaceState" : "pushState";
  window.history[method]({}, document.title, path);
}

/**
 * Token do link de aprovação. Aceita o link quebrado que sai quando o botão do template na Meta foi cadastrado
 * como ".../aprovar/{{1}}" (a Meta acrescenta outro {{1}} e o primeiro chega literal: /aprovar/%7B%7B1%7D%7D<token>).
 */
export function approvalTokenFromPath(pathname: string): string | null {
  let path = String(pathname || "");
  try { path = decodeURIComponent(path); } catch { /* caminho malformado: segue como veio */ }
  const match = path.replace(/\{\{\s*\d+\s*\}\}/g, "").match(/^\/aprovar\/([A-Za-z0-9_-]{30,64})\/?$/);
  return match ? match[1] : null;
}
