// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  mode: "meta" as "meta" | "ga4",
  listProperties: vi.fn(),
  startGoogle: vi.fn(),
}));

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: "amalie", name: "Amalie", role: "owner" }),
  getActiveClientId: () => "amalie",
  getActiveClientName: () => "Amalie",
  getActiveClientConfigurationWarning: () => null,
  MUGO_APP_NAME: "Mugô Dados",
}));

vi.mock("../app/connectionState", () => ({
  getActiveConnectionId: () => null,
  setActiveConnectionId: vi.fn(),
}));

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  const metaConnection = {
    id: "meta-generic", client_id: "amalie", provider: "meta", status: "connected",
    token_available: true, disconnected_at: null, metadata: { selected_ad_account_id: "act_1" },
  };
  const ga4Connection = {
    id: "ga4-existing", client_id: "amalie", provider: "ga4", status: "connected",
    token_available: true, disconnected_at: null, scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
    capabilities: { ga4_authorized: true, ga4_configured: false, ga4_status: "property_required", ads_authorized: false, ads_configured: false, ads_status: "not_connected" },
    metadata: {},
  };
  return {
    ...actual,
    listClientConnections: vi.fn(async () => ({ connections: mocks.mode === "meta" ? [{ id: "paid-1", platform: "meta_ads", connection_type: "paid", status: "active", ad_account_id: "act_1", ad_account_name: "Amalie Ads" }] : [] })),
    listGenericConnections: vi.fn(async () => ({ ok: true, client_id: "amalie", connections: [mocks.mode === "meta" ? metaConnection : ga4Connection] })),
    listGoogleGa4Properties: mocks.listProperties,
    startGoogleOAuth: mocks.startGoogle,
    getApiVersion: vi.fn(async () => ({ commit_sha: "test-sha", build_time: "test", environment: "test" })),
  };
});

import Onboarding from "./Onboarding";
import { ApiError } from "../app/api";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function renderOnboarding() {
  await act(async () => {
    root.render(<Onboarding isAuthenticated />);
  });
  await act(async () => Promise.resolve());
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mocks.listProperties.mockReset().mockResolvedValue({ ok: true, properties: [{ property: "properties/1", property_name: "Site Amalie" }] });
  mocks.startGoogle.mockReset();
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Onboarding integration actions", () => {
  it("opens manual Meta fields with Ads connected and organic pending", async () => {
    mocks.mode = "meta";
    await renderOnboarding();
    const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Configuração avançada por ID"));
    expect(button).toBeTruthy();
    await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container.textContent).toContain("Facebook Page ID");
    expect(container.textContent).toContain("Instagram Business Account ID");
    expect(container.textContent).toContain("Meta Ad Account ID");
    expect(container.textContent).toContain("Validar IDs");
    expect(container.textContent).toContain("Salvar ativos");
  });

  it("lists properties on an existing GA4 connection without starting OAuth", async () => {
    mocks.mode = "ga4";
    await renderOnboarding();
    const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Selecionar propriedade"));
    expect(button).toBeTruthy();
    await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(mocks.listProperties).toHaveBeenCalledWith("ga4-existing");
    expect(mocks.startGoogle).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Selecionar propriedade GA4");
  });

  it("offers reconnect only for GOOGLE_REAUTH_REQUIRED", async () => {
    mocks.mode = "ga4";
    mocks.listProperties.mockRejectedValueOnce(new ApiError("Autorização expirada.", {
      status: 409, code: "GOOGLE_REAUTH_REQUIRED", requestId: "req-reauth",
    }));
    await renderOnboarding();
    const select = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Selecionar propriedade"));
    await act(async () => select?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container.textContent).toContain("Reconectar Google");
    expect(container.textContent).toContain("GOOGLE_REAUTH_REQUIRED");
    expect(mocks.startGoogle).not.toHaveBeenCalled();
  });

  it("does not offer or start OAuth when the Admin API is disabled", async () => {
    mocks.mode = "ga4";
    mocks.listProperties.mockRejectedValueOnce(new ApiError("Analytics Admin API desabilitada.", {
      status: 409, code: "GOOGLE_ADMIN_API_DISABLED", requestId: "req-admin",
    }));
    await renderOnboarding();
    const select = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Selecionar propriedade"));
    await act(async () => select?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container.textContent).not.toContain("Reconectar Google");
    expect(container.textContent).toContain("GOOGLE_ADMIN_API_DISABLED");
    expect(mocks.startGoogle).not.toHaveBeenCalled();
  });
});
