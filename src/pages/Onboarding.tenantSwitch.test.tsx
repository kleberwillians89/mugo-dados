// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Empresa ativa mutável: simula a troca pelo seletor sem remontar a tela
// (o App renderiza o mesmo <Onboarding> para qualquer empresa).
const tenant = vi.hoisted(() => ({
  current: { id: "empresa-a", name: "Empresa A", role: "client_admin" },
}));

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => tenant.current,
  getActiveClientId: () => tenant.current.id,
  getActiveClientName: () => tenant.current.name,
  getActiveClientConfigurationWarning: () => null,
  MUGO_APP_NAME: "Mugô Dados",
}));

vi.mock("../app/connectionState", () => ({
  getActiveConnectionId: () => null,
  getSelectedConnectionId: () => null,
  setActiveConnectionId: vi.fn(),
  setSelectedConnectionId: vi.fn(),
}));

const discoveredA = {
  ok: true,
  handoff: "h-a",
  client_id: "empresa-a",
  meta_user: { id: "meta-user-a", name: "Autorizador A" },
  pages: [{ id: "page-a", page_id: "page-a", name: "Página Empresa A", page_name: "Página Empresa A", instagram: { id: "ig-a", username: "empresa_a" } }],
  page_count: 1,
  instagram_accounts: [{ ig_user_id: "ig-a", username: "empresa_a", business_id: "page-a", business_name: "Página Empresa A" }],
  ad_accounts: [{ ad_account_id: "act_a", ad_account_name: "Ads Empresa A" }],
  business_managers: [],
  scopes: ["business_management"],
};

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  return {
    ...actual,
    discoverClientMetaAssets: vi.fn(async () => discoveredA),
    listClientConnections: vi.fn(async () => ({ connections: [] })),
    listGenericConnections: vi.fn(async () => ({
      ok: true,
      client_id: tenant.current.id,
      connections: tenant.current.id === "empresa-a"
        ? [{ id: "auth-a", client_id: "empresa-a", provider: "meta", status: "selection_required", token_available: true, disconnected_at: null, metadata: { oauth_handoff: "h-a" } }]
        : [],
    })),
    getClientIntegrations: vi.fn(async () => ({ ok: true, client_id: tenant.current.id, integrations: [] })),
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

async function renderOnboarding() {
  await act(async () => {
    root.render(<Onboarding isAuthenticated />);
  });
  await flush();
}

beforeEach(() => {
  tenant.current = { id: "empresa-a", name: "Empresa A", role: "client_admin" };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  window.history.replaceState(
    {},
    "",
    "/?onboarding=1&client_id=empresa-a&meta_oauth=success&handoff=h-a&connection_id=auth-a"
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.history.replaceState({}, "", "/");
});

describe("Onboarding — troca de empresa com ativos Meta pendentes", () => {
  it("descarta Página, Instagram e Ads da empresa anterior ao trocar para outra empresa", async () => {
    await renderOnboarding();

    // Empresa A: retorno do OAuth carregou os ativos pendentes na tela.
    expect(container.textContent).toContain("Página Empresa A");
    expect(container.textContent).toContain("@empresa_a");
    expect(container.textContent).toContain("Ads Empresa A");
    expect(container.textContent).toContain("Autorizador A");

    // Troca para a Empresa B sem remontar o componente.
    tenant.current = { id: "empresa-b", name: "Empresa B", role: "client_admin" };
    await renderOnboarding();

    expect(container.textContent).toContain("Empresa B");
    expect(container.textContent).not.toContain("Página Empresa A");
    expect(container.textContent).not.toContain("@empresa_a");
    expect(container.textContent).not.toContain("Ads Empresa A");
    expect(container.textContent).not.toContain("Autorizador A");
  });
});
