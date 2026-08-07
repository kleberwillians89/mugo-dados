// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildDashboardCacheKey, clearDashboardCacheByPrefix, writeDashboardCache } from "../hooks/dashboard/cache";
import type { GenericConnection } from "../app/api";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => "amalie",
  getActiveClientName: () => "Amalie",
}));

vi.mock("../app/connectionState", () => ({
  getSelectedConnectionId: () => null,
}));

vi.mock("./Shopify", () => ({
  default: () => <div data-testid="shopify-page">Shopify carregado</div>,
}));

vi.mock("../app/api", () => ({
  listGenericConnections: vi.fn(() => new Promise(() => {})), // nunca resolve neste teste
}));

import Ecommerce from "./Ecommerce";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  clearDashboardCacheByPrefix("commerce-connection");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Ecommerce — nunca mostra 'Carregando e-commerce' quando já existe fonte conhecida em cache", () => {
  it("renderiza a Shopify imediatamente a partir do cache, mesmo com a revalidação pendurada", async () => {
    const cacheKey = buildDashboardCacheKey("commerce-connection", { clientId: "amalie" });
    const cachedConnection: GenericConnection = {
      id: "shopify-1",
      client_id: "amalie",
      provider: "shopify",
      status: "connected",
    } as GenericConnection;
    writeDashboardCache<GenericConnection | null>(cacheKey, cachedConnection, 300_000);

    await act(async () => {
      root.render(
        <Ecommerce
          isAuthenticated
          onLogout={() => {}}
          onOpenDashboard={() => {}}
          onOpenGoogleReport={() => {}}
        />
      );
    });

    expect(container.textContent).toContain("Shopify carregado");
    expect(container.textContent).not.toContain("Carregando e-commerce");
  });
});
