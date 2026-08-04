// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  mode: "meta" as "meta" | "ga4" | "google_ads",
  listProperties: vi.fn(),
  startGoogle: vi.fn(),
  validateMeta: vi.fn(),
  saveMeta: vi.fn(),
  listAds: vi.fn(),
  organicConfigured: false,
  selectedConnections: {} as Record<string, string>,
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
  getSelectedConnectionId: (_clientId: string, provider: string) => mocks.selectedConnections[provider] || null,
  setActiveConnectionId: vi.fn(),
  setSelectedConnectionId: vi.fn((_clientId: string, provider: string, connectionId: string | null) => {
    if (connectionId) mocks.selectedConnections[provider] = connectionId;
    else delete mocks.selectedConnections[provider];
  }),
}));

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  const metaConnection = {
    id: "meta-generic", client_id: "amalie", provider: "meta", status: "connected",
    token_available: true, disconnected_at: null, metadata: { selected_ad_account_id: "act_1" },
  };
  const disconnectedMetaConnection = {
    ...metaConnection, id: "meta-old", status: "disconnected", disconnected_at: "2026-08-01T00:00:00Z",
  };
  const ga4Connection = {
    id: "ga4-existing", client_id: "amalie", provider: "ga4", status: "connected",
    token_available: true, disconnected_at: null, scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
    capabilities: { ga4_authorized: true, ga4_configured: false, ga4_status: "property_required", ads_authorized: false, ads_configured: false, ads_status: "not_connected" },
    metadata: {},
  };
  const disconnectedAdsConnection = {
    id: "ads-old", client_id: "amalie", provider: "google_ads", status: "disconnected",
    token_available: false, disconnected_at: "2026-08-01T00:00:00Z",
    capabilities: { ga4_authorized: false, ga4_configured: false, ga4_status: "authorization_required", ads_authorized: false, ads_configured: false, ads_status: "not_connected" },
    metadata: {},
  };
  return {
    ...actual,
    listClientConnections: vi.fn(async () => ({ connections: mocks.mode === "meta" ? [
      { id: "paid-1", platform: "meta_ads", connection_type: "paid", status: "active", ad_account_id: "act_1", ad_account_name: "Amalie Ads" },
      ...(mocks.organicConfigured ? [{ id: "organic-1", platform: "instagram", connection_type: "organic", status: "active", ig_user_id: "178414000000001" }] : []),
    ] : [] })),
    listGenericConnections: vi.fn(async () => ({ ok: true, client_id: "amalie", connections: mocks.mode === "meta" ? [disconnectedMetaConnection, metaConnection] : mocks.mode === "google_ads" ? [disconnectedAdsConnection, ga4Connection] : [ga4Connection] })),
    listGoogleGa4Properties: mocks.listProperties,
    startGoogleOAuth: mocks.startGoogle,
    validateManualMetaAssets: mocks.validateMeta,
    saveManualMetaAssets: mocks.saveMeta,
    listGoogleAdsAccounts: mocks.listAds,
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

function changeInput(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

async function selectAuthorization(connectionId: string) {
  const select = [...container.querySelectorAll("select")].find((item) =>
    [...item.options].some((option) => option.value === connectionId)
  );
  expect(select).toBeTruthy();
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
    setter?.call(select, connectionId);
    select?.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mocks.listProperties.mockReset().mockResolvedValue({ ok: true, properties: [{ property: "properties/1", property_name: "Site Amalie" }] });
  mocks.startGoogle.mockReset();
  mocks.organicConfigured = false;
  mocks.selectedConnections = {};
  mocks.validateMeta.mockReset().mockResolvedValue({
    ok: true, page: { id: "123456789", name: "Amalie" },
    instagram: { id: "178414000000001", username: "amalie" }, ad_account: null,
  });
  mocks.saveMeta.mockReset().mockImplementation(async () => {
    mocks.organicConfigured = true;
    return { ok: true, initial_sync: { ok: true } };
  });
  mocks.listAds.mockReset();
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Onboarding integration actions", () => {
  it("never lists Ads accounts when only a disconnected Ads connection exists", async () => {
    mocks.mode = "google_ads";
    await renderOnboarding();
    expect(mocks.listAds).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Conectar Google Ads");
    expect(container.textContent).not.toContain("ads-old");
  });
  it("opens manual Meta fields with Ads connected and organic pending", async () => {
    mocks.mode = "meta";
    await renderOnboarding();
    await selectAuthorization("meta-generic");
    const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Configuração avançada por ID"));
    expect(button).toBeTruthy();
    await act(async () => button?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container.textContent).toContain("Facebook Page ID");
    expect(container.textContent).toContain("Instagram Business Account ID");
    expect(container.textContent).toContain("Meta Ad Account ID");
    expect(container.textContent).toContain("Validar IDs");
    expect(container.textContent).toContain("Salvar ativos");
    expect(container.textContent).toContain("Conexão Meta selecionada: meta-gen");
    expect(container.textContent).toContain("Tenant: amalie");
  });

  it("validates and saves manual Meta assets using the explicitly selected Amalie authorization", async () => {
    mocks.mode = "meta";
    await renderOnboarding();
    await selectAuthorization("meta-generic");
    const open = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Configuração avançada por ID"));
    await act(async () => open?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    const inputs = [...container.querySelectorAll("section.onboardingFinalizeCard input")];
    await act(async () => {
      const page = inputs[0] as HTMLInputElement;
      const instagram = inputs[1] as HTMLInputElement;
      changeInput(page, "123456789");
      changeInput(instagram, "178414000000001");
    });
    const validate = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Validar IDs"));
    await act(async () => validate?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(mocks.validateMeta).toHaveBeenCalledWith("meta-generic", expect.objectContaining({
      page_id: "123456789", instagram_id: "178414000000001",
    }));
    const save = [...container.querySelectorAll("button")].find((item) => item.textContent === "Salvar ativos");
    await act(async () => save?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(mocks.saveMeta).toHaveBeenCalledWith("meta-generic", expect.objectContaining({
      page_id: "123456789", instagram_id: "178414000000001",
    }));
    expect(container.textContent).toContain("Instagram orgânico configurado");
  });

  it("keeps the Meta form open when initial sync fails", async () => {
    mocks.mode = "meta";
    mocks.saveMeta.mockResolvedValueOnce({ ok: true, organic_connection_id: "organic-1", initial_sync: { ok: false, code: "META_GRAPH_UNAVAILABLE" } });
    await renderOnboarding();
    await selectAuthorization("meta-generic");
    const open = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Configuração avançada por ID"));
    await act(async () => open?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    const input = container.querySelector("section.onboardingFinalizeCard input") as HTMLInputElement;
    await act(async () => changeInput(input, "123456789"));
    const validate = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Validar IDs"));
    await act(async () => validate?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    const save = [...container.querySelectorAll("button")].find((item) => item.textContent === "Salvar ativos");
    await act(async () => save?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container.textContent).toContain("Configuração avançada por ID");
    expect(container.textContent).toContain("META_GRAPH_UNAVAILABLE");
  });

  it("removes a persisted disconnected Google Ads id without requesting accounts", async () => {
    mocks.mode = "google_ads";
    mocks.selectedConnections.google_ads = "ads-old";
    await renderOnboarding();
    expect(mocks.selectedConnections.google_ads).toBeUndefined();
    expect(mocks.listAds).not.toHaveBeenCalled();
  });

  it("lists properties on an existing GA4 connection without starting OAuth", async () => {
    mocks.mode = "ga4";
    await renderOnboarding();
    await selectAuthorization("ga4-existing");
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
    await selectAuthorization("ga4-existing");
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
    await selectAuthorization("ga4-existing");
    const select = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("Selecionar propriedade"));
    await act(async () => select?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container.textContent).not.toContain("Reconectar Google");
    expect(container.textContent).toContain("GOOGLE_ADMIN_API_DISABLED");
    expect(mocks.startGoogle).not.toHaveBeenCalled();
  });
});
