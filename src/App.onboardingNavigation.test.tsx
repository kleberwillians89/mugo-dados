// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Estado mutável do "backend" simulado. acceptInvitation() muda-o exatamente
// como a RPC real: cria a membership derivada da invitation e marca o convite
// como aceito. O client_id de destino vem SEMPRE daqui (autoridade do backend),
// nunca de um valor arbitrário do frontend.
const backend = vi.hoisted(() => ({
  session: null as unknown,
  memberships: [] as Array<{ client_id: string; role: string }>,
  clients: [] as Array<{ id: string; name: string; trade_name: string }>,
  pendingInvitations: [] as Array<Record<string, unknown>>,
  acceptedRole: "client_admin",
  platformAdmin: false,
}));

function supabaseResult(table: string) {
  if (table === "platform_admins") return { data: backend.platformAdmin ? { user_id: "user-1" } : null, error: null };
  if (table === "client_memberships") return { data: backend.memberships, error: null };
  if (table === "clients") return { data: backend.clients, error: null };
  return { data: [], error: null };
}

function supabaseChain(table: string) {
  const payload = () => Promise.resolve(supabaseResult(table));
  const obj: Record<string, unknown> = {
    select: () => obj,
    eq: () => obj,
    in: () => payload(),
    order: () => payload(),
    maybeSingle: () => payload(),
    then: (res: (v: unknown) => unknown, rej?: (e: unknown) => unknown) => payload().then(res, rej),
  };
  return obj;
}

vi.mock("./app/supabase", () => ({
  SUPABASE_AUTH_OPTIONS: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  getSupabaseBootstrapError: () => null,
  isLocalAuthEnabled: () => false,
  isLocalAuthAvailable: () => false,
  enableLocalAuth: () => {},
  disableLocalAuth: () => {},
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: backend.session }, error: null }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }),
      signOut: async () => ({ error: null }),
    },
    from: (table: string) => supabaseChain(table),
  },
}));

vi.mock("./app/api", () => ({
  ApiError: class ApiError extends Error {
    code = "";
    requestId = "";
  },
  setApiAccessToken: vi.fn(),
  listClients: vi.fn(async () => ({ clients: [] })),
  openPlatformCompany: vi.fn(async () => ({ ok: true })),
  getMyPendingInvitations: vi.fn(async () => ({ ok: true, invitations: backend.pendingInvitations })),
  acceptInvitation: vi.fn(async (invitationId: string) => {
    const invitation = backend.pendingInvitations.find((item) => item.id === invitationId);
    const clientId = String(invitation?.client_id || "roove");
    backend.memberships = [...backend.memberships, { client_id: clientId, role: backend.acceptedRole }];
    backend.clients = [...backend.clients, { id: clientId, name: "Roove", trade_name: "Roove" }];
    backend.pendingInvitations = [];
    return { ok: true, client_id: clientId, role: backend.acceptedRole };
  }),
}));

// activeClient real usa localStorage, que está indisponível neste jsdom
// (mesma causa dos testes de baseline já vermelhos). Store em memória.
const activeClientStore = vi.hoisted(() => ({ current: null as { id: string; name: string; role: string | null } | null }));
vi.mock("./app/activeClient", () => ({
  MUGO_APP_NAME: "Mugô Dados",
  canonicalizeClientId: (value: string | null | undefined) => String(value || "").trim(),
  getActiveClient: () => activeClientStore.current,
  getActiveClientName: () => activeClientStore.current?.name || "Cliente",
  getActiveClientId: () => activeClientStore.current?.id || "",
  setActiveClient: (client: { id: string; name: string; role?: string | null }) => {
    activeClientStore.current = { id: client.id, name: client.name, role: client.role ?? null };
  },
  clearTenantBrowserState: () => {
    activeClientStore.current = null;
  },
}));

vi.mock("./app/connectionState", () => ({ setActiveConnectionId: vi.fn() }));
vi.mock("./app/DashboardDataContext", () => ({
  DashboardDataProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("./pages/Login", () => ({ default: () => React.createElement("div", { "data-testid": "login-stub" }) }));
// Expõe a query vista pelo Onboarding no momento em que ele renderiza — é ali
// que o handoff do OAuth precisa estar disponível.
vi.mock("./pages/Onboarding", () => ({
  default: () => React.createElement("div", { "data-testid": "onboarding-stub", "data-search": window.location.search }),
}));
vi.mock("./pages/Dashboard", () => ({ default: () => React.createElement("div", { "data-testid": "dashboard-stub" }) }));
vi.mock("./pages/GoogleAnalytics", () => ({ default: () => React.createElement("div", { "data-testid": "ga-stub" }) }));
vi.mock("./pages/Ecommerce", () => ({ default: () => React.createElement("div", { "data-testid": "ecommerce-stub" }) }));
vi.mock("./pages/Companies", () => ({
  default: (props: { onOpenCompany: (company: Record<string, string>, route?: string) => void }) =>
    React.createElement(
      "button",
      {
        "data-testid": "companies-stub",
        type: "button",
        onClick: () => props.onOpenCompany({ id: "mugo-new", name: "Mugô", trade_name: "Mugô" }, "integrations"),
      },
      "Abrir Mugô"
    ),
}));
vi.mock("./pages/Intelligence", () => ({ default: () => React.createElement("div", { "data-testid": "intelligence-stub" }) }));
vi.mock("./pages/NotFound", () => ({ default: () => React.createElement("div", { "data-testid": "notfound-stub" }) }));

import App from "./App";
import { getActiveClientId } from "./app/activeClient";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function flush() {
  // A suíte completa executa vários ambientes jsdom em paralelo. Aguarda o
  // bootstrap assíncrono terminar sem depender da velocidade do worker.
  for (let i = 0; i < 24; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function renderApp() {
  await act(async () => {
    root.render(React.createElement(App));
  });
  await flush();
}

function findButton(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((item) => item.textContent?.trim() === text);
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  window.history.replaceState({}, "", "/meta?code=magiclink-token");
  activeClientStore.current = null;
  backend.session = {
    access_token: "token-abc",
    user: { id: "user-1", email: "cliente@empresa.com", user_metadata: {} },
  };
  backend.memberships = [{ client_id: "amalie", role: "client_admin" }];
  backend.clients = [{ id: "amalie", name: "Amalie", trade_name: "Amalie" }];
  backend.pendingInvitations = [
    { id: "inv-1", client_id: "roove", role: "client_admin", company_name: "Roove", expires_at: null },
  ];
  backend.acceptedRole = "client_admin";
  backend.platformAdmin = false;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.history.replaceState({}, "", "/");
});

describe("App — convergência do onboarding (link/convite → Integrações)", () => {
  it("cliente existente: aceita a invitation e cai no Onboarding do tenant da invitation", async () => {
    await renderApp();

    // Bootstrap parou na tela de aceitação de convite, com o tenant antigo ativo.
    expect(container.textContent).toContain("Você foi convidado para uma empresa");
    expect(getActiveClientId()).toBe("amalie");

    await act(async () => {
      findButton("Aceitar convite")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();

    // Tenant de destino = o da invitation aceita (autoridade do backend),
    // NÃO o activeClient anterior ("amalie").
    expect(getActiveClientId()).toBe("roove");
    expect(container.querySelector('[data-testid="onboarding-stub"]')).toBeTruthy();
    expect(window.location.pathname).toBe("/integracoes");
  });

  it("viewer: aceita a invitation, tenant correto fica ativo, mas segue read-only para o dashboard", async () => {
    backend.acceptedRole = "viewer";
    await renderApp();

    await act(async () => {
      findButton("Aceitar convite")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();

    expect(getActiveClientId()).toBe("roove");
    expect(container.querySelector('[data-testid="dashboard-stub"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="onboarding-stub"]')).toBeNull();
    // viewer não ganha a aba de Integrações.
    expect(findButton("Integrações")).toBeUndefined();
  });

  it("novo usuário por link de onboarding (invitation_id nos metadados) entra direto nas Integrações", async () => {
    // Trigger do backend já criou a membership; nenhum convite pendente.
    backend.memberships = [{ client_id: "roove", role: "client_admin" }];
    backend.clients = [{ id: "roove", name: "Roove", trade_name: "Roove" }];
    backend.pendingInvitations = [];
    backend.session = {
      access_token: "token-abc",
      user: { id: "user-2", email: "novo@empresa.com", user_metadata: { invitation_id: "inv-9", client_id: "roove", role: "client_admin" } },
    };

    await renderApp();

    expect(getActiveClientId()).toBe("roove");
    expect(container.querySelector('[data-testid="onboarding-stub"]')).toBeTruthy();
  });

  it("viewer não alcança /integracoes nem por navegação direta", async () => {
    backend.acceptedRole = "viewer";
    backend.memberships = [{ client_id: "roove", role: "viewer" }];
    backend.clients = [{ id: "roove", name: "Roove", trade_name: "Roove" }];
    backend.pendingInvitations = [];
    window.history.replaceState({}, "", "/integracoes");

    await renderApp();

    expect(container.querySelector('[data-testid="onboarding-stub"]')).toBeNull();
    expect(container.querySelector('[data-testid="dashboard-stub"]')).toBeTruthy();
  });
});

describe("App — retorno do OAuth Meta", () => {
  it("preserva a query do callback e abre o Onboarding em vez do Dashboard", async () => {
    const callbackQuery = "?onboarding=1&client_id=test-client&meta_oauth=success&handoff=h-1&connection_id=c-1";
    backend.memberships = [{ client_id: "test-client", role: "client_admin" }];
    backend.clients = [{ id: "test-client", name: "Test Client", trade_name: "Test Client" }];
    backend.pendingInvitations = [];
    activeClientStore.current = { id: "test-client", name: "Test Client", role: "client_admin" };
    window.history.replaceState({}, "", `/${callbackQuery}`);

    await renderApp();

    const onboarding = container.querySelector('[data-testid="onboarding-stub"]');
    expect(onboarding).toBeTruthy();
    expect(container.querySelector('[data-testid="dashboard-stub"]')).toBeNull();
    // O Onboarding renderizou com o handoff ainda na URL — é ele quem consome
    // e limpa esses parâmetros.
    expect(onboarding?.getAttribute("data-search")).toBe(callbackQuery);
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe(callbackQuery);
    expect(getActiveClientId()).toBe("test-client");
  });
});

describe("App — empresa recém-aberta pela administração", () => {
  function switcherNames(): string[] {
    const switcher = container.querySelector(".clientSwitcher");
    const trigger = switcher?.querySelector<HTMLButtonElement>(".clientSwitcherTrigger");
    act(() => {
      trigger?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    return [...(switcher?.querySelectorAll(".clientSwitcherOptionName") || [])].map((item) => item.textContent || "");
  }

  async function openMugoFromCompanies() {
    await act(async () => {
      container.querySelector('[data-testid="companies-stub"]')?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
  }

  beforeEach(() => {
    backend.platformAdmin = true;
    backend.memberships = [];
    backend.clients = [{ id: "amalie", name: "Amalie", trade_name: "Amalie" }];
    backend.pendingInvitations = [];
    window.history.replaceState({}, "", "/empresas");
  });

  it("entra no seletor sem F5 e vira a empresa ativa usada pelo OAuth", async () => {
    await renderApp();
    await openMugoFromCompanies();

    expect(getActiveClientId()).toBe("mugo-new");
    expect(container.querySelector('[data-testid="onboarding-stub"]')).toBeTruthy();
    expect(container.querySelector(".clientSwitcher .clientSwitcherName")?.textContent).toBe("Mugô");
    expect(switcherNames()).toEqual(["Amalie", "Mugô"]);
  });

  it("não duplica a empresa quando ela já está na lista do bootstrap", async () => {
    backend.clients = [
      { id: "amalie", name: "Amalie", trade_name: "Amalie" },
      { id: "mugo-new", name: "Mugô", trade_name: "Mugô" },
    ];
    await renderApp();
    await openMugoFromCompanies();

    expect(getActiveClientId()).toBe("mugo-new");
    expect(switcherNames().filter((name) => name === "Mugô")).toHaveLength(1);
  });
});
