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
  google: "google", origins: "origins", calendar: "calendar", approval: "calendar", brand_ai: "brand_ai",
  media: "media", social_report: "social_report", tasks: "tasks", clipping: "clipping", creators: "creators",
  engagement: "engagement", users: "team", campaigns: "social_media",
};

/** Módulos liberados só pela equipe Mugô: não vêm de "acesso total" nem do papel (mesma regra do backend). */
export const OPT_IN_CODES = new Set(["social_media.view", "social_media.edit"]);
