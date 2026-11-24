export type AppRoute =
  | "home"
  | "process_planning"
  | "process_content"
  | "process_campaign"
  | "process_analysis"
  | "meta"
  | "google"
  | "ecommerce"
  | "customers"
  | "goals"
  | "calendar"
  | "approval"
  | "internal_approval"
  | "final_approval"
  | "media"
  | "tasks"
  | "briefing"
  | "library"
  | "planning"
  | "production"
  | "central"
  | "radar"
  | "brand_health"
  | "channels"
  | "tiktok"
  | "pinterest"
  | "linkedin"
  | "benchmark"
  | "clipping"
  | "engagement"
  | "social_report"
  | "brand_ai"
  | "mugo_ia"
  | "campaigns"
  | "redacao"
  | "creators"
  | "automations"
  | "integrations"
  | "origins"
  | "whatsapp"
  | "intelligence"
  | "companies"
  | "ai_usage"
  | "integration_health"
  | "email_marketing"
  | "capture"
  | "customer_value"
  | "ai_actions"
  | "plan"
  | "plans_admin"
  | "users"
  | "not_found";

export type PublicAppRoute = "privacy" | "data_deletion" | "data_protection" | "terms";

export function getPublicAppRouteFromPath(pathname: string): PublicAppRoute | null {
  const normalized = String(pathname || "/").trim().toLowerCase().replace(/\/+$/, "") || "/";
  if (normalized === "/en/privacy") return "privacy";
  if (normalized === "/en/terms") return "terms";
  if (normalized === "/en/data-deletion") return "data_deletion";
  if (normalized === "/privacidade") return "privacy";
  if (normalized === "/exclusao-de-dados") return "data_deletion";
  if (normalized === "/protecao-de-dados") return "data_protection";
  if (normalized === "/termos-de-uso" || normalized === "/termos") return "terms";
  return null;
}

export function getAppRouteFromPath(pathname: string): AppRoute {
  const normalized = String(pathname || "/").trim().toLowerCase();
  if (normalized === "/" || normalized === "") return "home";
  if (normalized === "/inicio" || normalized.startsWith("/inicio/")) return "home";
  if (normalized === "/planejar" || normalized.startsWith("/planejar/")) return "process_planning";
  if (normalized === "/criar-conteudo" || normalized.startsWith("/criar-conteudo/")) return "process_content";
  if (normalized === "/lancar-campanha" || normalized.startsWith("/lancar-campanha/")) return "process_campaign";
  if (normalized === "/analisar-resultados" || normalized.startsWith("/analisar-resultados/")) return "process_analysis";
  if (normalized.startsWith("/empresas")) return "companies";
  if (normalized === "/consumo-ia" || normalized.startsWith("/consumo-ia/")) return "ai_usage";
  if (normalized === "/saude-integracoes" || normalized.startsWith("/saude-integracoes/")) return "integration_health";
  if (normalized === "/captacao" || normalized.startsWith("/captacao/")) return "capture";
  if (normalized === "/email-marketing" || normalized.startsWith("/email-marketing/")) return "email_marketing";
  if (normalized === "/acoes-ia" || normalized.startsWith("/acoes-ia/")) return "ai_actions";
  if (normalized === "/plano" || normalized.startsWith("/plano/")) return "plan";
  if (normalized === "/admin/planos" || normalized.startsWith("/admin/planos/")) return "plans_admin";
  if (normalized === "/usuarios" || normalized.startsWith("/usuarios/")) return "users";
  if (normalized === "/metas" || normalized.startsWith("/metas/")) return "goals";
  if (normalized === "/calendario" || normalized.startsWith("/calendario/")) return "calendar";
  // Aprovação mora no Calendário (visão Fluxo); o endereço antigo abre o Calendário já no Fluxo.
  if (normalized === "/aprovacao" || normalized.startsWith("/aprovacao/")) return "calendar";
  if (normalized === "/aprovacao-interna" || normalized.startsWith("/aprovacao-interna/")) return "internal_approval";
  if (normalized === "/aprovacao-final" || normalized.startsWith("/aprovacao-final/")) return "final_approval";
  if (normalized === "/midia" || normalized.startsWith("/midia/")) return "media";
  if (normalized === "/tarefas" || normalized.startsWith("/tarefas/")) return "tasks";
  if (normalized === "/briefing" || normalized.startsWith("/briefing/")) return "briefing";
  if (normalized === "/biblioteca" || normalized.startsWith("/biblioteca/")) return "library";
  if (normalized === "/planejamento" || normalized.startsWith("/planejamento/")) return "planning";
  // Evento = Produção (RTV e eventos) da iAgência.
  if (normalized === "/evento" || normalized.startsWith("/evento/") || normalized === "/producao" || normalized.startsWith("/producao/")) return "production";
  if (normalized === "/central" || normalized.startsWith("/central/")) return "central";
  if (normalized === "/benchmark" || normalized.startsWith("/benchmark/")) return "benchmark";
  if (normalized === "/radar" || normalized.startsWith("/radar/")) return "radar";
  if (normalized === "/saude-da-marca" || normalized.startsWith("/saude-da-marca/")) return "brand_health";
  if (normalized === "/tiktok" || normalized.startsWith("/tiktok/")) return "tiktok";
  if (normalized === "/pinterest" || normalized.startsWith("/pinterest/")) return "pinterest";
  if (normalized === "/linkedin" || normalized.startsWith("/linkedin/")) return "linkedin";
  if (normalized === "/canais" || normalized.startsWith("/canais/")) return "channels";
  if (normalized === "/clipping" || normalized.startsWith("/clipping/")) return "clipping";
  if (normalized === "/comentarios" || normalized.startsWith("/comentarios/")) return "engagement";
  // Contexto da Marca (Configurações). /ia-da-marca é o endereço antigo e continua abrindo a mesma tela.
  if (normalized === "/contexto-da-marca" || normalized.startsWith("/contexto-da-marca/")) return "brand_ai";
  if (normalized === "/ia-da-marca" || normalized.startsWith("/ia-da-marca/")) return "brand_ai";
  if (normalized === "/mugo-ia" || normalized.startsWith("/mugo-ia/") || normalized === "/mugoverso-ia" || normalized.startsWith("/mugoverso-ia/")) return "mugo_ia";
  if (normalized === "/relatorio-social" || normalized.startsWith("/relatorio-social/")) return "social_report";
  // Social Media (antes Redação): o endereço antigo continua abrindo a mesma tela.
  if (normalized === "/social-media" || normalized.startsWith("/social-media/")) return "campaigns";
  // Redação (editor de texto da iAgência): página própria, fora de Social Media.
  if (normalized === "/redacao" || normalized.startsWith("/redacao/")) return "redacao";
  if (normalized === "/criadores" || normalized.startsWith("/criadores/")) return "creators";
  if (normalized === "/automacoes" || normalized.startsWith("/automacoes/")) return "automations";
  // Atendimento mora no painel Cliente do Calendário; o endereço antigo continua funcionando.
  if (normalized === "/atendimento" || normalized.startsWith("/atendimento/")) return "calendar";
  if (normalized.startsWith("/meta")) return "meta";
  if (
    normalized.startsWith("/dashboard") ||
    normalized.startsWith("/overview") ||
    normalized.startsWith("/visao-geral")
  ) return "meta";
  if (normalized.startsWith("/integracoes")) return "integrations";
  if (normalized.startsWith("/origem-das-vendas")) return "origins";
  if (normalized === "/crm" || normalized.startsWith("/crm/origem")) return "origins";
  if (normalized.startsWith("/crm/clientes")) return "customers";
  if (normalized.startsWith("/crm/ltv")) return "customer_value";
  if (normalized === "/whatsapp" || normalized.startsWith("/whatsapp/")) return "whatsapp";
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
  if (route === "home") return "/inicio";
  if (route === "process_planning") return "/planejar";
  if (route === "process_content") return "/criar-conteudo";
  if (route === "process_campaign") return "/lancar-campanha";
  if (route === "process_analysis") return "/analisar-resultados";
  if (route === "companies") return "/empresas";
  if (route === "ai_usage") return "/consumo-ia";
  if (route === "integration_health") return "/saude-integracoes";
  if (route === "capture") return "/captacao";
  if (route === "email_marketing") return "/email-marketing";
  if (route === "ai_actions") return "/acoes-ia";
  if (route === "plan") return "/plano";
  if (route === "plans_admin") return "/admin/planos";
  if (route === "users") return "/usuarios";
  if (route === "meta") return "/meta";
  if (route === "integrations") return "/integracoes";
  if (route === "origins") return "/crm";
  if (route === "whatsapp") return "/whatsapp";
  if (route === "intelligence") return "/inteligencia";
  if (route === "google") return "/google";
  if (route === "ecommerce") return "/ecommerce";
  if (route === "goals") return "/metas";
  if (route === "calendar") return "/calendario";
  if (route === "approval") return "/calendario";
  if (route === "internal_approval") return "/aprovacao-interna";
  if (route === "final_approval") return "/aprovacao-final";
  if (route === "media") return "/midia";
  if (route === "tasks") return "/tarefas";
  if (route === "briefing") return "/briefing";
  if (route === "library") return "/biblioteca";
  if (route === "planning") return "/planejamento";
  if (route === "production") return "/evento";
  if (route === "central") return "/central";
  if (route === "benchmark") return "/benchmark";
  if (route === "radar") return "/radar";
  if (route === "brand_health") return "/saude-da-marca";
  if (route === "channels") return "/canais";
  if (route === "tiktok") return "/tiktok";
  if (route === "pinterest") return "/pinterest";
  if (route === "linkedin") return "/linkedin";
  if (route === "clipping") return "/clipping";
  if (route === "engagement") return "/comentarios";
  if (route === "social_report") return "/relatorio-social";
  if (route === "brand_ai") return "/contexto-da-marca";
  if (route === "mugo_ia") return "/mugo-ia";
  if (route === "campaigns") return "/social-media";
  if (route === "redacao") return "/redacao";
  if (route === "creators") return "/criadores";
  if (route === "automations") return "/automacoes";
  if (route === "customers") return "/crm/clientes";
  if (route === "customer_value") return "/crm/ltv";
  if (route === "not_found") return "/404";
  return "/meta";
}

/** Quantas telas do Mugoverso existem antes desta no histórico (0 = chegou de fora, link direto ou primeira tela). */
export function appHistoryDepth(): number {
  const state = window.history.state as { mugoDepth?: unknown } | null;
  return typeof state?.mugoDepth === "number" && state.mugoDepth > 0 ? state.mugoDepth : 0;
}

export function navigateToAppRoute(route: AppRoute, options?: { replace?: boolean }) {
  const path = getPathForRoute(route);
  if (options?.replace) window.history.replaceState({ mugoDepth: appHistoryDepth() }, document.title, path);
  else window.history.pushState({ mugoDepth: appHistoryDepth() + 1 }, document.title, path);
}

/**
 * Botão "Voltar" das páginas internas: volta à tela anterior do Mugoverso (o navegador restaura a URL, com filtros
 * e período que estiverem nela). Sem histórico interno (link direto, nova aba), vai para um destino seguro: o Início.
 */
export function goBackInApp(fallback: AppRoute = "home") {
  if (appHistoryDepth() > 0) { window.history.back(); return; }
  navigateToAppRoute(fallback);
  window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
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
