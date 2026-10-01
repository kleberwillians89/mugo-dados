// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  tenant: "vinhos",
  listAds: vi.fn(),
  selectAds: vi.fn(),
  syncGoogle: vi.fn(),
  listProperties: vi.fn(),
  selectedConnections: {} as Record<string, Record<string, string>>,
  adsMetadata: {} as Record<string, unknown>,
}));

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: mocks.tenant, name: mocks.tenant, role: "agency_admin" }),
  getActiveClientId: () => mocks.tenant,
  getActiveClientName: () => mocks.tenant,
  getActiveClientConfigurationWarning: () => null,
  MUGO_APP_NAME: "Mugô Dados",
}));

vi.mock("../app/connectionState", () => ({
  getActiveConnectionId: () => null,
  getSelectedConnectionId: (clientId: string, provider: string) => mocks.selectedConnections[clientId]?.[provider] || null,
  setActiveConnectionId: vi.fn(),
  setSelectedConnectionId: vi.fn((clientId: string, provider: string, connectionId: string | null) => {
    const tenant = { ...(mocks.selectedConnections[clientId] || {}) };
    if (connectionId) tenant[provider] = connectionId;
    else delete tenant[provider];
    mocks.selectedConnections[clientId] = tenant;
  }),
}));

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  const adsConnection = () => ({
    id: `ads-${mocks.tenant}`, client_id: mocks.tenant, provider: "google_ads", status: "selection_required",
    token_available: true, disconnected_at: null, account_name: "mugo.agencia@gmail.com",
    scopes: ["https://www.googleapis.com/auth/adwords"],
    capabilities: { ga4_authorized: false, ga4_configured: false, ga4_status: "authorization_required", ads_authorized: true, ads_configured: false, ads_status: "account_required" },
    metadata: { ...mocks.adsMetadata },
  });
  return {
    ...actual,
    listClientConnections: vi.fn(async () => ({ connections: [] })),
    listGenericConnections: vi.fn(async () => ({ ok: true, client_id: mocks.tenant, connections: [adsConnection()] })),
    listGoogleGa4Properties: mocks.listProperties,
    listGoogleAdsAccounts: mocks.listAds,
    selectGoogleAdsAccount: mocks.selectAds,
    syncGoogleConnection: mocks.syncGoogle,
    getApiVersion: vi.fn(async () => ({ commit_sha: "test-sha", build_time: "test", environment: "test" })),
  };
});

import Onboarding from "./Onboarding";
import { ApiError } from "../app/api";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const CURAVINO = {
  customer_id: "1234567890", resource_name: "customers/1234567890", descriptive_name: "Curavino",
  currency_code: "BRL", time_zone: "America/Sao_Paulo", is_manager: false, status: "ENABLED",
  access: "manager", login_customer_id: "5550001111", manager_customer_id: "5550001111", manager_name: "Mugô MCC",
};
const MCC = {
  customer_id: "5550001111", resource_name: "customers/5550001111", descriptive_name: "Mugô MCC",
  is_manager: true, status: "ENABLED", access: "direct", login_customer_id: null,
};
const DIRECT = {
  customer_id: "9990001111", resource_name: "customers/9990001111", descriptive_name: "Outra conta",
  is_manager: false, status: "CANCELED", access: "direct", login_customer_id: null,
};

async function renderOnboarding() {
  await act(async () => {
    root.render(<Onboarding isAuthenticated />);
  });
  await act(async () => Promise.resolve());
}

async function flush() {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

function buttonByText(text: string) {
  return [...container.querySelectorAll("button")].find((item) => item.textContent?.trim() === text);
}

async function click(target: HTMLElement | undefined) {
  expect(target).toBeTruthy();
  await act(async () => { target?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
  await flush();
}

function adsCombobox(): HTMLElement {
  const label = [...container.querySelectorAll(".assetComboboxLabel")].find((item) => item.textContent === "Conta Google Ads");
  const box = label?.closest(".assetCombobox") as HTMLElement | null;
  expect(box).toBeTruthy();
  return box as HTMLElement;
}

async function openAdsDropdown() {
  const input = adsCombobox().querySelector("input") as HTMLInputElement;
  await act(async () => { input.focus(); });
  return input;
}

async function pickAdsAccount(customerId: string) {
  const input = await openAdsDropdown();
  const option = adsCombobox().querySelector(`li[id$="-option-${customerId}"]`) as HTMLElement | null;
  expect(option).toBeTruthy();
  await act(async () => {
    option?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
  });
  await flush();
  return input;
}

async function selectAuthorization(connectionId: string) {
  const inputs = [...container.querySelectorAll<HTMLInputElement>(".assetCombobox input")];
  let option: HTMLElement | null = null;
  for (const input of inputs) {
    await act(async () => { input.focus(); });
    option = container.querySelector(`li[id$="-option-${connectionId}"]`);
    if (option) break;
    await act(async () => { input.blur(); });
  }
  expect(option).toBeTruthy();
  await act(async () => {
    option?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function openAdsPicker() {
  await renderOnboarding();
  await selectAuthorization(`ads-${mocks.tenant}`);
  await click(buttonByText("Selecionar conta"));
}

function connectButton() {
  return buttonByText("Conectar Google Ads") as HTMLButtonElement | undefined;
}

beforeEach(() => {
  mocks.tenant = "vinhos";
  mocks.selectedConnections = {};
  mocks.adsMetadata = {};
  mocks.listAds.mockReset().mockResolvedValue({ ok: true, accounts: [MCC, CURAVINO, DIRECT] });
  mocks.selectAds.mockReset().mockResolvedValue({ ok: true });
  mocks.syncGoogle.mockReset().mockResolvedValue({ ok: true });
  mocks.listProperties.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Google Ads — seletor de conta", () => {
  it("lista as contas da conexão do tenant ativo vinhos e identifica MCC e acesso via MCC", async () => {
    await openAdsPicker();
    expect(mocks.listAds).toHaveBeenCalledTimes(1);
    const [connection, clientId] = mocks.listAds.mock.calls[0];
    expect(connection).toMatchObject({ id: "ads-vinhos", client_id: "vinhos" });
    expect(clientId).toBe("vinhos");
    await openAdsDropdown();
    const box = adsCombobox();
    expect(box.textContent).toContain("Mugô MCC — 555-000-1111");
    expect(box.textContent).toContain("Conta administradora");
    expect(box.textContent).toContain("Curavino — 123-456-7890");
    expect(box.textContent).toContain("Via conta administradora Mugô MCC · 555-000-1111");
    expect(box.textContent).toContain("Cancelada");
  });

  it("selecionar conta atualiza o campo, fecha o dropdown, mostra o resumo e habilita o CTA", async () => {
    await openAdsPicker();
    expect(connectButton()?.disabled).toBe(true);
    const input = await pickAdsAccount(CURAVINO.customer_id);
    expect(input.value).toBe("Curavino — 123-456-7890");
    expect(adsCombobox().querySelector(".assetComboboxList")).toBeNull();
    const summary = container.querySelector('[data-testid="google-ads-selected"]');
    expect(summary?.textContent).toContain("✓ Curavino");
    expect(summary?.textContent).toContain("ID: 123-456-7890");
    expect(summary?.textContent).toContain("Acesso via conta administradora 555-000-1111");
    expect(connectButton()?.disabled).toBe(false);
    // Nenhum efeito sobrescreve a seleção nos ciclos seguintes.
    await flush();
    await renderOnboarding();
    expect(input.value).toBe("Curavino — 123-456-7890");
    expect(connectButton()?.disabled).toBe(false);
  });

  it("confirmar persiste a conta com login-customer-id da MCC e dispara a primeira sincronização", async () => {
    await openAdsPicker();
    await pickAdsAccount(CURAVINO.customer_id);
    await click(connectButton());
    expect(mocks.selectAds).toHaveBeenCalledWith("ads-vinhos", "1234567890", "5550001111");
    expect(mocks.syncGoogle).toHaveBeenCalledWith("ads-vinhos");
    expect(container.textContent).toContain("Conta Google Ads conectada e sincronizada.");
    expect(container.textContent).not.toContain("Selecionar conta Google Ads");
  });

  it("conta direta é persistida sem login-customer-id", async () => {
    await openAdsPicker();
    await pickAdsAccount(DIRECT.customer_id);
    await click(connectButton());
    expect(mocks.selectAds).toHaveBeenCalledWith("ads-vinhos", "9990001111", null);
  });

  it("conta administradora (MCC) é identificada e não pode ser conectada como conta de mídia", async () => {
    await openAdsPicker();
    await pickAdsAccount(MCC.customer_id);
    const summary = container.querySelector('[data-testid="google-ads-selected"]');
    expect(summary?.textContent).toContain("Conta administradora: não possui campanhas próprias");
    expect(connectButton()?.disabled).toBe(true);
    expect(mocks.selectAds).not.toHaveBeenCalled();
  });

  it("falha na primeira sincronização é exibida sem desfazer a seleção salva", async () => {
    mocks.syncGoogle.mockRejectedValueOnce(new ApiError("O Developer Token do Google Ads foi recusado.", {
      status: 403, code: "GOOGLE_ADS_DEVELOPER_TOKEN_NOT_APPROVED", requestId: "req-sync",
    }));
    await openAdsPicker();
    await pickAdsAccount(CURAVINO.customer_id);
    await click(connectButton());
    expect(mocks.selectAds).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Conta Google Ads salva, mas a primeira sincronização falhou");
    expect(container.textContent).toContain("GOOGLE_ADS_DEVELOPER_TOKEN_NOT_APPROVED");
  });

  it("erro da Google Ads API aparece no seletor e não vira 'Nenhuma conta encontrada'", async () => {
    mocks.listAds.mockRejectedValueOnce(new ApiError("A Google Ads limitou temporariamente as solicitações.", {
      status: 429, code: "GOOGLE_RATE_LIMITED", requestId: "req-429",
    }));
    await openAdsPicker();
    const box = adsCombobox();
    expect(box.querySelector('[role="alert"]')?.textContent).toContain("GOOGLE_RATE_LIMITED");
    await openAdsDropdown();
    expect(box.textContent).toContain("Não foi possível carregar as contas.");
    expect(box.textContent).not.toContain("Nenhuma conta encontrada.");
    expect(connectButton()?.disabled).toBe(true);
  });

  it("lista vazia (sucesso) mostra 'Nenhuma conta encontrada' sem erro", async () => {
    mocks.listAds.mockResolvedValueOnce({ ok: true, accounts: [] });
    await openAdsPicker();
    const box = adsCombobox();
    expect(box.querySelector('[role="alert"]')).toBeNull();
    await openAdsDropdown();
    expect(box.textContent).toContain("Nenhuma conta encontrada.");
  });

  it("trocar de empresa limpa a seleção Google Ads transitória", async () => {
    await openAdsPicker();
    await pickAdsAccount(CURAVINO.customer_id);
    expect(container.querySelector('[data-testid="google-ads-selected"]')).not.toBeNull();

    mocks.tenant = "roove";
    await renderOnboarding();
    await flush();
    expect(container.textContent).not.toContain("Selecionar conta Google Ads");
    expect(container.querySelector('[data-testid="google-ads-selected"]')).toBeNull();
    expect(container.textContent).not.toContain("Curavino");
    expect(mocks.selectAds).not.toHaveBeenCalled();
    expect(mocks.selectedConnections.roove?.google_ads).toBeUndefined();
  });
});
