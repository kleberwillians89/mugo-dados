// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

const WARNING = "Não foi possível listar os Businesses desta autorização. Os ativos acessíveis diretamente foram listados normalmente.";

// /me/businesses falhou: só ativos diretos + aviso seguro do backend.
const discovered = {
  ok: true,
  handoff: "h-direto",
  client_id: "ruah",
  meta_user: { id: "meta-user", name: "Pessoa Autorizada" },
  business_managers: [],
  discovery_warnings: [{ code: "META_BUSINESSES_UNAVAILABLE", status: "permission_denied", message: WARNING }],
  pages: [],
  instagram_accounts: [],
  ad_accounts: [
    { ad_account_id: "act_direta", ad_account_name: "Conta direta", access_status: "accessible", discovery_sources: ["me_adaccounts"], businesses: [] },
  ],
  scopes: ["business_management", "ads_read"],
};

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  return {
    ...actual,
    discoverClientMetaAssets: vi.fn(async () => discovered),
    linkClientAssets: vi.fn(async () => ({ ok: true, connections: [] })),
    listClientConnections: vi.fn(async () => ({ connections: [] })),
    listGenericConnections: vi.fn(async () => ({
      ok: true,
      client_id: "ruah",
      connections: [{ id: "auth-ruah", client_id: "ruah", provider: "meta", status: "selection_required", token_available: true, disconnected_at: null, metadata: { oauth_handoff: "h-direto" } }],
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

beforeEach(async () => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  window.history.replaceState({}, "", "/?onboarding=1&client_id=ruah&meta_oauth=success&handoff=h-direto&connection_id=auth-ruah");
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

describe("Onboarding — /me/businesses indisponível", () => {
  it("mostra os ativos diretos e o aviso seguro, sem afirmar que não há Gerenciador de Negócios", () => {
    expect(container.querySelector('[data-testid="meta-discovery-warning"]')?.textContent).toBe(WARNING);
    expect(container.textContent).toContain("Conta direta");
    expect(container.textContent).not.toContain("não possui acesso a um Gerenciador de Negócios");
  });
});
