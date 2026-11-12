/** Regras de Usuários sem dependência da API (login, menu): seguras para importar em qualquer tela. */

/** Login por usuário: "joao.vendas" vira, só internamente, o e-mail abaixo (mesma regra do backend). */
export const INTERNAL_LOGIN_DOMAIN = "acesso.mugo.ag";
export const USERNAME_RE = /^[a-z0-9._-]{3,32}$/;

export function normalizeLoginIdentifier(raw: string): string {
  const value = raw.trim().toLowerCase();
  if (!value || value.includes("@")) return value;
  return `${value}@${INTERNAL_LOGIN_DOMAIN}`;
}

/** Tela (rota do app) → código de permissão para ver. Telas fora da lista não dependem de permissão. */
export const ROUTE_MODULE: Record<string, string> = {
  central: "central", goals: "central", ecommerce: "ecommerce", customers: "customers", meta: "meta",
  google: "google", origins: "origins", whatsapp: "origins", email_marketing: "customers", customer_value: "customers", ai_actions: "customers", plan: "central", calendar: "calendar", approval: "calendar", brand_ai: "brand_ai", mugo_ia: "brand_ai",
  media: "media", social_report: "social_report", tasks: "tasks", briefing: "tasks", library: "calendar", planning: "tasks", production: "tasks", clipping: "clipping", radar: "clipping", benchmark: "clipping", creators: "creators",
  engagement: "engagement", users: "team", campaigns: "social_media", redacao: "social_media",
};

/** Módulos liberados só pela equipe Mugô: não vêm de "acesso total" nem do papel (mesma regra do backend). */
export const OPT_IN_CODES = new Set(["social_media.view", "social_media.edit", "tasks.approve"]);

/** Social Media reúne recursos distintos sem fundir suas permissões. */
export function canViewAppRoute(route: string, can: (code: string) => boolean): boolean {
  if (route === "campaigns") return can("social_media.view") || can("calendar.view");
  // Planejamento e Evento são internos: equipe Mugô ou quem aprova internamente (mesma regra do backend).
  if (route === "planning" || route === "production") return can("tasks.approve");
  const module = ROUTE_MODULE[route];
  return !module || can(`${module}.view`);
}
