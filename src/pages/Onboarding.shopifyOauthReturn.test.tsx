// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  syncShopifyConnection: vi.fn(async () => ({ ok: true })),
  startShopifyOAuth: vi.fn(async () => ({ authorization_url: "https://shopify.test/oauth" })),
  disconnectGenericConnection: vi.fn(async () => ({ ok: true })),
  selectedConnections: {} as Record<string, string>,
  role: "agency_admin",
}));

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: "amalie", name: "Amalie", role: mocks.role }),
  getActiveClientId: () => "amalie",
  getActiveClientName: () => "Amalie",
  getActiveClientConfigurationWarning: () => null,
  MUGO_APP_NAME: "Mugô Dados",
}));

vi.mock("../app/connectionState", () => ({
  getActiveConnectionId: () => null,
  getSelectedConnectionId: (_clientId: string, provider: string) => mocks.selectedConnections[provider] || null,
  setActiveConnectionId: vi.fn(),
  setSelectedConnectionId: vi.fn((_clientId: string, provider: string, connectionId: string | null) => {
    if (connectionId) mocks.selectedConnections[provider] = connectionId;
    else delete mocks.selectedConnections[provider];
  }),
}));

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  const shopifyConnection = {
    id: "shopify-conn-1", client_id: "amalie", provider: "shopify", status: "connected",
    token_available: true, disconnected_at: null, scopes: ["read_orders", "read_all_orders", "read_customers", "read_products"], metadata: { shop_domain: "amalie-6421.myshopify.com" },
  };
  return {
    ...actual,
    listClientConnections: vi.fn(async () => ({ connections: [] })),
    listGenericConnections: vi.fn(async () => ({ ok: true, client_id: "amalie", connections: [shopifyConnection] })),
    getClientIntegrations: vi.fn(async () => ({
      ok: true,
      client_id: "amalie",
      connections: [
        {
          provider: "shopify",
          connection_id: "shopify-conn-1",
          status: "connected",
          authorization_status: "valid",
          sync_status: "sync_success",
          account: { domain: "amalie-6421.myshopify.com", name: "Amalie" },
          assets: { shop_domain: "amalie-6421.myshopify.com" },
          last_sync_at: null,
          last_successful_sync_at: null,
          last_error: null,
          updated_at: "2026-08-08T00:00:00Z",
        },
      ],
    })),
    getApiVersion: vi.fn(async () => ({ commit_sha: "test-sha", build_time: "test", environment: "test" })),
    syncShopifyConnection: mocks.syncShopifyConnection,
    startShopifyOAuth: mocks.startShopifyOAuth,
    disconnectGenericConnection: mocks.disconnectGenericConnection,
  };
});

import Onboarding from "./Onboarding";

let container: HTMLDivElement | null = null;
let root: ReturnType<typeof createRoot> | null = null;

beforeEach(() => {
  mocks.syncShopifyConnection.mockClear();
  mocks.selectedConnections = {};
  mocks.role = "agency_admin";
  window.history.pushState({}, "", "/?shopify_oauth=success&connection_id=shopify-conn-1&client_id=amalie");
});

afterEach(() => {
  if (root) {
    act(() => {
      root!.unmount();
    });
    root = null;
  }
  if (container) {
    container.remove();
    container = null;
  }
  window.history.pushState({}, "", "/");
  vi.clearAllMocks();
});

async function mount() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(<Onboarding isAuthenticated />);
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("Onboarding — retorno do OAuth Shopify não dispara backfill duplicado", () => {
  it("shopify_oauth=success nunca chama POST /sync (o callback do backend já iniciou o backfill)", async () => {
    await mount();
    expect(mocks.syncShopifyConnection).not.toHaveBeenCalled();
  });

  it("persiste a seleção local da conexão Shopify a partir do retorno do OAuth", async () => {
    await mount();
    expect(mocks.selectedConnections.shopify).toBe("shopify-conn-1");
  });

  it("nunca mostra erro vermelho para o retorno de sucesso do OAuth Shopify", async () => {
    await mount();
    expect(container?.textContent).not.toMatch(/Falha ao processar o retorno do OAuth/);
  });

  it("expõe atualizar permissões e desconectar para a conexão Shopify existente", async () => {
    await mount();
    const manage = [...container!.querySelectorAll("button")].find((button) => button.textContent === "Gerenciar") as HTMLButtonElement;
    await act(async () => manage.click());
    expect(container?.textContent).toContain("Atualizar permissões");
    expect(container?.textContent).toContain("Desconectar");
  });

  it("não habilita gerenciamento de integrações para client_admin", async () => {
    mocks.role = "client_admin";
    await mount();
    const manage = [...container!.querySelectorAll("button")].find((button) => button.textContent === "Gerenciar") as HTMLButtonElement;
    await act(async () => manage.click());
    const update = [...container!.querySelectorAll("button")].find((button) => button.textContent === "Atualizar permissões") as HTMLButtonElement;
    expect(update.disabled).toBe(true);
  });
});
