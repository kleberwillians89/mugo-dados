// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Caso RÜAH em produção (fixtures): Instagram conectado, Meta Ads pendente,
// nenhuma conta paga salva. "Selecionar conta" precisa relistar na Meta.
const RUAH_BUSINESS = "2633867063339117";
const RUAH_AD_ACCOUNT = "act_1391863696277834";

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: "ruah", name: "RÜAH", role: "client_admin" }),
  getActiveClientId: () => "ruah",
  getActiveClientName: () => "RÜAH",
  getActiveClientConfigurationWarning: () => null,
  MUGO_APP_NAME: "Mugô Dados",
}));

vi.mock("../app/connectionState", () => ({
  getActiveConnectionId: () => null,
  // A autorização Meta da empresa já está escolhida (estado da produção).
  getSelectedConnectionId: (_clientId: string, provider: string) => (provider === "meta" ? "auth-ruah" : null),
  setActiveConnectionId: vi.fn(),
  setSelectedConnectionId: vi.fn(),
}));

const rediscovered = {
  ok: true,
  handoff: "h-novo",
  client_id: "ruah",
  meta_user: { id: "meta-user", name: "Pessoa Autorizada" },
  business_managers: [{
    business_id: RUAH_BUSINESS, business_name: "RŪAH",
    discovery: { owned_ad_accounts: { status: "permission_denied" }, client_ad_accounts: { status: "ok", count: 1 } },
  }],
  pages: [],
  instagram_accounts: [],
  ad_accounts: [
    {
      ad_account_id: RUAH_AD_ACCOUNT, ad_account_name: "RŪAH Ads", access_status: "accessible", account_status: 1,
      discovery_sources: ["business_client"], businesses: [{ business_id: RUAH_BUSINESS, business_name: "RŪAH", relation: "client" }],
    },
    // Verificação transitória falhou: continua visível e selecionável.
    { ad_account_id: "act_incerta", ad_account_name: "Conta não verificada", access_status: "unverified", account_status: 2, discovery_sources: ["business_client"], businesses: [] },
    { ad_account_id: "act_bloqueada", ad_account_name: "Conta sem acesso", access_status: "restricted", discovery_sources: ["business_client"], businesses: [] },
  ],
  scopes: ["business_management", "ads_read"],
};

const api = vi.hoisted(() => ({
  savedPaid: [] as Array<Record<string, unknown>>,
  linkClientAssets: vi.fn(async () => ({ ok: true, connections: [] })),
  discoverExistingMetaAdAccounts: vi.fn(async () => rediscovered),
  listClientMetaAdsAccounts: vi.fn(async () => ({ ok: true, accounts: [] as Array<Record<string, unknown>> })),
}));

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  return {
    ...actual,
    linkClientAssets: api.linkClientAssets,
    discoverExistingMetaAdAccounts: api.discoverExistingMetaAdAccounts,
    listClientMetaAdsAccounts: api.listClientMetaAdsAccounts,
    listClientConnections: vi.fn(async () => ({ connections: [] })),
    listGenericConnections: vi.fn(async () => ({
      ok: true,
      client_id: "ruah",
      connections: [{
        id: "auth-ruah", client_id: "ruah", provider: "meta", status: "connected", token_available: true, disconnected_at: null,
        metadata: { selected_instagram_id: "ig-ruah", selected_instagram_username: "ruah_parfums", organic_status: "connected", ads_status: "asset_required" },
      }],
    })),
    getClientIntegrations: vi.fn(async () => ({ ok: true, client_id: "ruah", integrations: [] })),
    getApiVersion: vi.fn(async () => ({ commit_sha: "test-sha", build_time: "test", environment: "test" })),
  };
});

import Onboarding from "./Onboarding";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function flush() {
  for (let i = 0; i < 12; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

function checkbox(text: string): HTMLInputElement | null {
  const label = [...container.querySelectorAll("label.onboardingCheck")].find((item) => item.textContent?.includes(text));
  return label?.querySelector("input") || null;
}

async function clickButton(text: string) {
  const button = [...container.querySelectorAll("button")].find((item) => item.textContent === text);
  expect(button, `botão "${text}"`).toBeTruthy();
  await act(async () => {
    button?.click();
  });
  await flush();
}

beforeEach(async () => {
  api.linkClientAssets.mockClear();
  api.discoverExistingMetaAdAccounts.mockClear();
  api.listClientMetaAdsAccounts.mockClear();
  api.listClientMetaAdsAccounts.mockImplementation(async () => ({ ok: true, accounts: [] }));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  window.history.replaceState({}, "", "/?onboarding=1&client_id=ruah");
  await act(async () => {
    root.render(<Onboarding isAuthenticated />);
  });
  await flush();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.history.replaceState({}, "", "/");
});

describe("Onboarding — Meta Ads pendente com conexão existente", () => {
  it("sem conta paga salva, Selecionar conta relista na Meta e mostra a conta do Business", async () => {
    await clickButton("Selecionar conta");
    expect(api.discoverExistingMetaAdAccounts).toHaveBeenCalledWith("auth-ruah");
    expect(container.textContent).toContain(RUAH_AD_ACCOUNT);
    expect(container.textContent).not.toContain("não retornou nenhuma conta de anúncios");
    // Nenhum filtro visual por Business, status, origem ou verificação.
    expect(checkbox("RŪAH Ads")?.disabled).toBe(false);
    expect(checkbox("Conta não verificada")?.disabled).toBe(false);
    expect(checkbox("Conta sem acesso")?.disabled).toBe(true);
  });

  it("a conta escolhida segue para a gravação com o ad_account_id correto, no handoff novo", async () => {
    await clickButton("Selecionar conta");
    await act(async () => {
      checkbox("RŪAH Ads")?.click();
    });
    await clickButton("Salvar conexão e importar dados");
    expect(api.linkClientAssets).toHaveBeenCalledWith({
      handoff: "h-novo",
      page_ids: [],
      instagram_ig_user_ids: [],
      ad_account_ids: [RUAH_AD_ACCOUNT],
    });
  });

  it("com conta paga já salva, mantém o seletor atual sem relistar", async () => {
    api.listClientMetaAdsAccounts.mockImplementation(async () => ({
      ok: true,
      accounts: [{ connection_id: "paid-1", ad_account_id: RUAH_AD_ACCOUNT, ad_account_name: "RŪAH Ads", status: "active", scopes: ["ads_read"] }],
    }));
    await clickButton("Selecionar conta");
    expect(api.discoverExistingMetaAdAccounts).not.toHaveBeenCalled();
  });
});
