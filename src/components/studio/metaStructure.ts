import type { AdPayload, MetaCatalog, MetaLocation, MetaObjective, MetaStructure } from "../../app/metaAds";

/** Regras de tela do criador igual ao Gerenciador. Quem valida de verdade é a Meta, na criação pausada. */
export const needsEvent = (m: Pick<MetaStructure, "performance_goal" | "conversion_location">) =>
  m.conversion_location === "WEBSITE" && (m.performance_goal === "OFFSITE_CONVERSIONS" || m.performance_goal === "VALUE");
export const needsVideo = (goal: string) => goal === "THRUPLAY" || goal === "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS";
export const bidOptions = (goal: string) => goal === "VALUE"
  ? ["LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_MIN_ROAS"] : ["LOWEST_COST_WITHOUT_CAP", "COST_CAP", "LOWEST_COST_WITH_BID_CAP"];
const EVENT_DEFAULT: Partial<Record<MetaObjective, string>> = { OUTCOME_SALES: "PURCHASE", OUTCOME_LEADS: "LEAD", OUTCOME_ENGAGEMENT: "CONTENT_VIEW" };

/** Rascunho sem o bloco (só acontece antes do servidor responder): mesmo padrão da publicação antiga. */
export function metaOf(p: AdPayload): MetaStructure {
  return p.meta || {
    objective: "OUTCOME_TRAFFIC", special_ad_categories: [], budget_level: "campaign", budget_type: "daily", budget: p.daily_budget,
    bid_strategy: "LOWEST_COST_WITHOUT_CAP", bid_amount: null, roas_floor: null, conversion_location: "WEBSITE", messaging_apps: [],
    performance_goal: "LINK_CLICKS", conversion_event: null, app: null, lead_form: null, phone_number: null, has_end_date: true, use_existing_post: false,
  };
}

/** Locais de conversão do objetivo, na ordem do Gerenciador. App só aparece se a conta tiver app. */
export function locationsFor(catalog: MetaCatalog, objective: MetaObjective, hasApps: boolean): MetaLocation[] {
  const allowed = catalog.matrix[objective] || {};
  return catalog.location_order.filter((loc) => allowed[loc] && (loc !== "APP" || hasApps || objective === "OUTCOME_APP_PROMOTION"));
}
export const goalsFor = (catalog: MetaCatalog, objective: MetaObjective, location: MetaLocation) => catalog.matrix[objective]?.[location] || [];

/** Ajusta o conjunto quando muda algo acima (como o Gerenciador: cai na primeira opção válida). */
export function normalizeMeta(catalog: MetaCatalog, m: MetaStructure): MetaStructure {
  const locations = Object.keys(catalog.matrix[m.objective] || {}) as MetaLocation[];
  const location = locations.includes(m.conversion_location) ? m.conversion_location : locations[0];
  const goals = goalsFor(catalog, m.objective, location);
  const goal = goals.includes(m.performance_goal) ? m.performance_goal : goals[0];
  const event = needsEvent({ performance_goal: goal, conversion_location: location })
    ? (goal === "VALUE" ? "PURCHASE" : m.conversion_event || EVENT_DEFAULT[m.objective] || "PURCHASE") : null;
  const bid = bidOptions(goal).includes(m.bid_strategy) ? m.bid_strategy : "LOWEST_COST_WITHOUT_CAP";
  return {
    ...m, conversion_location: location, performance_goal: goal, conversion_event: event, bid_strategy: bid as MetaStructure["bid_strategy"],
    messaging_apps: location === "MESSAGING" ? (m.messaging_apps.length ? m.messaging_apps : ["WHATSAPP"]) : [],
    has_end_date: m.budget_type === "lifetime" ? true : m.has_end_date,
  };
}

/** Botões do anúncio para o local escolhido (lista do servidor, com os nomes da Meta). */
export function ctasFor(catalog: MetaCatalog, m: MetaStructure): string[] {
  if (m.conversion_location === "MESSAGING" && m.messaging_apps.length === 1 && m.messaging_apps[0] !== "MESSENGER")
    return catalog.ctas_by_location[`MESSAGING:${m.messaging_apps[0]}`] || [];
  return catalog.ctas_by_location[m.conversion_location] || [];
}

/** Destino fixo (o link do anúncio não é um site escolhido pela pessoa). */
export const fixedDestination = (m: MetaStructure) => !["WEBSITE", "NONE", "ON_POST"].includes(m.conversion_location);

/** Verba por dia equivalente, para comparar com o resto da plataforma. */
export function dailyEquivalent(m: MetaStructure, start: string, end: string): number {
  if (m.budget_type !== "lifetime") return m.budget;
  const days = Math.max(1, Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000) + 1);
  return Math.round((m.budget / days) * 100) / 100;
}
