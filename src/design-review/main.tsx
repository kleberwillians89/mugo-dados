// HARNESS DE REVISÃO VISUAL — somente desenvolvimento.
// Renderiza telas reais (login, convite, shell global, Ecommerce, Integrações) com
// respostas de API simuladas (dados de exemplo). Não é entrada do build de
// produção (vite.config usa só index.html) e nenhum mock sai daqui.
// Uso: http://127.0.0.1:5173/design-review.html (índice com todas as URLs)

import React from "react";
import ReactDOM from "react-dom/client";
import { setActiveClient } from "../app/activeClient";
import { setApiAccessToken } from "../app/api";
import { setActiveConnectionId, setSelectedConnectionId } from "../app/connectionState";
import { buildDashboardCacheKey, writeDashboardCache } from "../hooks/dashboard/cache";
import {
  REVIEW_COMPANIES,
  REVIEW_PROFILES,
  REVIEW_CHANNEL_SCENARIOS,
  REVIEW_SCENARIOS,
  reviewChannelSnapshot,
  reviewGa4Campaigns,
  reviewGa4Channels,
  reviewInstagramComments,
  reviewInstagramMedia,
  reviewInstagramMonthly,
  reviewCanonicalIntegrations,
  reviewGenericConnections,
  reviewMetaConnections,
  reviewMetaDiscovery,
  reviewOrders,
  reviewShopifyCustomers,
  reviewShopifyReport,
  reviewShopifySnapshot,
  reviewSummary,
  type ReviewChannelScenario,
  type ReviewProfile,
  type ReviewScenario,
} from "./fixtures";

import "../index.css";
import "../styles/fonts.css";
import "../styles/mugo.tokens.css";
import "../styles/design-system.css";
import "../styles/App.css";
import "../styles/shell.css";
import "../components/mugo-logo.css";
import "./review.css";
import ReviewScreen from "./ReviewScreen";

const params = new URLSearchParams(window.location.search);
const screen = params.get("tela") || "indice";
const requestedScenario = params.get("cenario") as ReviewScenario | null;
const scenario: ReviewScenario = REVIEW_SCENARIOS.some((item) => item.id === requestedScenario) ? requestedScenario! : "padrao";
// Telas de canal (Meta, Google Ads, GA4) têm cenários próprios no mesmo ?cenario=.
const CHANNEL_SCREENS = ["meta", "google-ads", "ga4"];
const isChannelScreen = CHANNEL_SCREENS.includes(screen);
const channelScenario: ReviewChannelScenario =
  REVIEW_CHANNEL_SCENARIOS.find((item) => item.id === (requestedScenario as string | null))?.id || "padrao";
const profile: ReviewProfile = (["agencia", "cliente", "viewer"] as const).find((item) => item === params.get("perfil")) || "agencia";
const showBanner = params.get("banner") !== "0";

// Empresas do perfil: agência vê todas as de exemplo; cliente/viewer, só as suas.
const companies = profile === "agencia"
  ? REVIEW_COMPANIES
  : params.get("empresas") === "2"
    ? REVIEW_COMPANIES.slice(0, 2)
    : [REVIEW_COMPANIES.find((company) => company.client_id === params.get("empresa")) || REVIEW_COMPANIES[0]];
const initialCompany = companies.find((company) => company.client_id === params.get("empresa")) || companies[0];

setActiveClient({ id: initialCompany.client_id, name: initialCompany.name, role: REVIEW_PROFILES[profile].role });
// Autorizações já escolhidas (como depois de uma conexão concluída no app real).
for (const company of companies) {
  setSelectedConnectionId(company.client_id, "meta", "exemplo-meta");
  setSelectedConnectionId(company.client_id, "ga4", "exemplo-ga4");
  setSelectedConnectionId(company.client_id, "google_ads", "exemplo-ads");
}
setActiveConnectionId("exemplo-ig");
// Token fictício só em memória: toda chamada /api/ é respondida pelo mock abaixo.
setApiAccessToken("revisao-visual");
try {
  window.sessionStorage.clear();
} catch {
  // Sem storage: a página só não reaproveita cache.
}
// Shopify (Roove): o read model vem do cache de sessão que o próprio
// DashboardDataProvider lê ao iniciar — sem Supabase no harness.
const reviewToday = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
// Canais: read model de exemplo por empresa (Roove soma o Shopify ao mesmo snapshot).
for (const company of companies) {
  const channels = reviewChannelSnapshot(company.client_id, reviewToday, isChannelScreen ? channelScenario : "padrao");
  const shopify = company.client_id === "roove" ? reviewShopifySnapshot("roove", reviewToday) : null;
  const shopifyByDay = new Map((shopify?.daily || []).map((row) => [row.metric_date, row]));
  writeDashboardCache(
    buildDashboardCacheKey("read-model-ytd-v2", { clientId: company.client_id }),
    {
      ...channels,
      daily: channels.daily.map((row) => {
        const store = shopifyByDay.get(row.metric_date);
        return store ? { ...row, ...Object.fromEntries(Object.entries(store).filter(([key]) => key.startsWith("shopify_"))) } : row;
      }),
      sources: [...channels.sources, ...(shopify?.sources || [])],
      products: shopify?.products || [],
    },
    24 * 60 * 60 * 1000
  );
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function companyName(clientId: string): string {
  return REVIEW_COMPANIES.find((company) => company.client_id === clientId)?.name || "Empresa";
}

const realFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, window.location.origin);
  if (!url.pathname.startsWith("/api/")) return realFetch(input, init);
  await new Promise((resolve) => window.setTimeout(resolve, 300));
  if (scenario === "carregando" && url.pathname.startsWith("/api/fbits/")) return new Promise<Response>(() => undefined);
  const channelApi = ["/api/media", "/api/comments", "/api/media/monthly", "/api/months", "/api/google/ga4/channels", "/api/google/ga4/campaigns"];
  if (isChannelScreen && channelApi.includes(url.pathname)) {
    if (channelScenario === "carregando") return new Promise<Response>(() => undefined);
    if (channelScenario === "erro") return json({ ok: false, detail: "Falha simulada" }, 500);
    const empty = channelScenario === "sem-dados" || channelScenario === "desconectado";
    const periodStart = url.searchParams.get("start") || reviewToday;
    const periodEnd = url.searchParams.get("end") || reviewToday;
    if (url.pathname === "/api/media") return json(empty ? { ok: true, media: [] } : reviewInstagramMedia(periodStart, periodEnd));
    if (url.pathname === "/api/comments") return json(empty ? { ok: true, comments: [], top_words: [], total: 0 } : reviewInstagramComments());
    if (url.pathname === "/api/media/monthly") return json(empty ? { ok: true, months: [] } : reviewInstagramMonthly(reviewToday));
    if (url.pathname === "/api/months") return json({ ok: true, months: empty ? [] : reviewInstagramMonthly(reviewToday).months.map((row) => row.month) });
    if (url.pathname === "/api/google/ga4/channels") return json(empty ? { ok: true, items: [] } : reviewGa4Channels(periodStart, periodEnd));
    return json(empty ? { ok: true, items: [] } : reviewGa4Campaigns(periodStart, periodEnd));
  }
  const clientMatch = /^\/api\/clients\/([^/]+)\//.exec(url.pathname);
  const clientId = clientMatch ? decodeURIComponent(clientMatch[1]) : initialCompany.client_id;
  const start = url.searchParams.get("start") || "";
  const end = url.searchParams.get("end") || "";
  if (url.pathname.endsWith("/integrations")) return json(reviewCanonicalIntegrations(clientId, companyName(clientId), scenario === "pendente", isChannelScreen ? channelScenario : "padrao"));
  if (url.pathname.endsWith("/connections") && clientMatch) return json(reviewMetaConnections(clientId, companyName(clientId)));
  if (url.pathname === "/api/connections") return json(reviewGenericConnections(clientId, companyName(clientId)));
  if (url.pathname === "/api/version") return json({ ok: true, commit_sha: "unknown" });
  if (url.pathname === "/api/oauth/meta/discover-assets") {
    const discoveryClient = url.searchParams.get("client_id") || initialCompany.client_id;
    return json(reviewMetaDiscovery(discoveryClient, companyName(discoveryClient)));
  }
  if (url.pathname === "/api/fbits/dashboard") {
    return scenario === "erro" ? json({ ok: false, detail: "Falha simulada" }, 500) : json(reviewSummary(scenario, start, end));
  }
  if (url.pathname === "/api/fbits/orders") return json(reviewOrders(scenario, start, end));
  if (url.pathname.includes("/fbits/sync")) return json({ ok: true, scheduled: true }, 202);
  if (url.pathname === "/api/shopify/report") return json(reviewShopifyReport(clientId, start, end));
  if (url.pathname === "/api/shopify/customers") return json(reviewShopifyCustomers(clientId, start, end));
  if (/^\/api\/oauth\/shopify\/[^/]+\/sync$/.test(url.pathname)) return json({ ok: true });
  // Aceite de convite: mesmas respostas da rota real (accept_user_invitation), por ?estado=.
  const inviteMatch = /^\/api\/invitations\/([^/]+)\/accept$/.exec(url.pathname);
  if (inviteMatch) {
    const inviteState = params.get("estado") || "padrao";
    if (inviteState === "aceitando") return new Promise<Response>(() => undefined);
    if (inviteState === "invalido") return json({ detail: "Convite não encontrado." }, 404);
    if (inviteState === "expirado") return json({ detail: "Este convite expirou. Peça um novo link à Mugô." }, 409);
    if (inviteState === "erro") return json({ detail: "Não foi possível aceitar o convite." }, 400);
    const inviteId = decodeURIComponent(inviteMatch[1]);
    return json({
      ok: true,
      client_id: inviteId === "convite-roove" ? "roove" : inviteId === "convite-sem-nome" ? "c-9f2" : "origami",
      role: inviteId === "convite-origami" ? "client_admin" : "viewer",
    });
  }
  return json({ ok: false, detail: "Rota não simulada no harness." }, 404);
};

// ?abrir=gaveta|empresas|conta|aceitar: aciona o controle real (clique no botão) para revisão/captura.
const OPEN_TARGETS: Record<string, string> = {
  gaveta: ".appTopbarMenu",
  empresas: ".appSidebar .clientSwitcherTrigger",
  conta: ".appSidebar .userMenuTrigger",
  aceitar: ".inviteAccept",
};
const openTarget = OPEN_TARGETS[params.get("abrir") || ""];
if (openTarget) {
  window.setTimeout(() => document.querySelector<HTMLElement>(openTarget)?.click(), 1200);
}

const scrollTarget = Number(params.get("y") || 0);
if (scrollTarget > 0) window.setTimeout(() => window.scrollTo(0, scrollTarget), 1500);

// ?debug=overflow: lista na tela os elementos que passam da largura da janela.
if (params.get("debug") === "overflow") {
  window.setTimeout(() => {
    const limit = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.right > limit + 1 && getComputedStyle(element).visibility !== "hidden";
      })
      .slice(0, 25)
      .map((element) => `${element.tagName.toLowerCase()}.${String(element.className || "").toString().split(" ").join(".")} → ${Math.round(element.getBoundingClientRect().right)}px (w ${Math.round(element.getBoundingClientRect().width)})`);
    const panel = document.createElement("pre");
    panel.style.cssText = "position:fixed;inset:0;z-index:9999;margin:0;padding:12px;background:#fff;color:#000;font:11px/1.4 monospace;white-space:pre-wrap;overflow:auto";
    panel.textContent = `viewport ${limit}px · scrollWidth ${document.documentElement.scrollWidth}px\n` + (offenders.join("\n") || "nenhum elemento passa da largura");
    document.body.appendChild(panel);
  }, 2500);
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ReviewScreen
      screen={screen}
      loginState={params.get("estado") || "padrao"}
      profile={profile}
      companies={companies}
      initialCompanyId={initialCompany.client_id}
      scenario={scenario}
      channelScenario={channelScenario}
      showBanner={showBanner}
    />
  </React.StrictMode>
);
