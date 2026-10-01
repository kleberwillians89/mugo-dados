// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// IDs do caso RÜAH e da Mugô: só fixtures de apresentação.
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
  getSelectedConnectionId: () => null,
  setActiveConnectionId: vi.fn(),
  setSelectedConnectionId: vi.fn(),
}));

const discovered = {
  ok: true,
  handoff: "h-ruah",
  client_id: "ruah",
  meta_user: { id: "meta-user", name: "Pessoa Autorizada" },
  business_managers: [
    { business_id: RUAH_BUSINESS, business_name: "RÜAH", discovery: { owned_ad_accounts: { status: "ok", count: 2 } } },
    { business_id: "biz-bloqueado", business_name: "Bloqueado", discovery: { owned_ad_accounts: { status: "permission_denied" } } },
    { business_id: "biz-vazio", business_name: "Vazio", discovery: { owned_ad_accounts: { status: "ok", count: 0 } } },
  ],
  pages: [{
    id: "page-ruah", page_id: "page-ruah", name: "RÜAH Perfumaria", page_name: "RÜAH Perfumaria",
    instagram: { id: "ig-ruah", username: "ruah" },
    businesses: [{ business_id: RUAH_BUSINESS, business_name: "RÜAH", relation: "owned" }],
    access_status: "accessible",
  }],
  instagram_accounts: [{ ig_user_id: "ig-ruah", username: "ruah", business_id: "page-ruah", business_name: "RÜAH Perfumaria" }],
  ad_accounts: [
    {
      ad_account_id: RUAH_AD_ACCOUNT, ad_account_name: "RÜAH Ads", access_status: "accessible",
      discovery_sources: ["business_owned"], businesses: [{ business_id: RUAH_BUSINESS, business_name: "RÜAH", relation: "owned" }],
    },
    {
      ad_account_id: "act_bloqueada", ad_account_name: "Conta sem acesso", access_status: "restricted",
      discovery_sources: ["business_owned"], businesses: [{ business_id: RUAH_BUSINESS, business_name: "RÜAH", relation: "owned" }],
    },
    { ad_account_id: "act_direta", ad_account_name: "Conta direta", access_status: "accessible", discovery_sources: ["me_adaccounts"], businesses: [] },
  ],
  scopes: ["business_management", "ads_read"],
};

const linkClientAssets = vi.hoisted(() => vi.fn(async () => ({ ok: true, connections: [] })));

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  return {
    ...actual,
    discoverClientMetaAssets: vi.fn(async () => discovered),
    linkClientAssets,
    listClientConnections: vi.fn(async () => ({ connections: [] })),
    listGenericConnections: vi.fn(async () => ({
      ok: true,
      client_id: "ruah",
      connections: [{ id: "auth-ruah", client_id: "ruah", provider: "meta", status: "selection_required", token_available: true, disconnected_at: null, metadata: { oauth_handoff: "h-ruah" } }],
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

beforeEach(async () => {
  linkClientAssets.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  window.history.replaceState({}, "", "/?onboarding=1&client_id=ruah&meta_oauth=success&handoff=h-ruah&connection_id=auth-ruah");
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

describe("Onboarding — ativos Meta agrupados por Business", () => {
  it("mostra cada Business com seus ativos, uma única vez, e os diretos ao final", () => {
    const groups = [...container.querySelectorAll("section.metaAssetGroup")];
    expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
      "Business RÜAH", "Business Bloqueado", "Ativos diretamente acessíveis",
    ]);
    expect(groups[0].textContent).toContain(`Business ${RUAH_BUSINESS}`);
    expect(groups[0].textContent).toContain("RÜAH Perfumaria");
    expect(groups[0].textContent).toContain("@ruah");
    expect(groups[0].textContent).toContain(RUAH_AD_ACCOUNT);
    expect(groups[1].textContent).toContain("A autorização atual não permite listar as contas de anúncio deste Business.");
    expect(groups[2].textContent).toContain("Outros ativos diretamente acessíveis");
    expect(groups[2].textContent).toContain("Conta direta");
    expect(container.textContent).toContain("Sem ativos para esta autorização: Vazio.");
    const occurrences = container.textContent?.split(RUAH_AD_ACCOUNT).length ?? 0;
    expect(occurrences - 1).toBe(1);
  });

  it("ativo bloqueado por permissão aparece com o aviso e não pode ser escolhido", () => {
    expect(checkbox("Conta sem acesso")?.disabled).toBe(true);
    expect(container.textContent).toContain("Encontrado, mas sua autorização atual não permite acessar todos os dados deste ativo.");
    expect(checkbox("RÜAH Ads")?.disabled).toBe(false);
  });

  it("nada é salvo sem escolha explícita; a escolha vai para o handoff do tenant atual", async () => {
    expect(linkClientAssets).not.toHaveBeenCalled();
    await act(async () => {
      checkbox("RÜAH Ads")?.click();
    });
    const save = [...container.querySelectorAll("button")].find((item) => item.textContent === "Salvar conexão e importar dados");
    await act(async () => {
      save?.click();
    });
    await flush();
    expect(linkClientAssets).toHaveBeenCalledTimes(1);
    expect(linkClientAssets).toHaveBeenCalledWith({
      handoff: "h-ruah",
      page_ids: [],
      instagram_ig_user_ids: [],
      ad_account_ids: [RUAH_AD_ACCOUNT],
    });
  });
});
