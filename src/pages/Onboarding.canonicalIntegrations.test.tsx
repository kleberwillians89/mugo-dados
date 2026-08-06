// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  activeClientId: "amalie",
  canonicalResponse: null as unknown,
  shouldRejectNext: false,
}));

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: mocks.activeClientId, name: "Amalie", role: "owner" }),
  getActiveClientId: () => mocks.activeClientId,
  getActiveClientName: () => "Amalie",
  getActiveClientConfigurationWarning: () => null,
  MUGO_APP_NAME: "Mugô Dados",
}));

vi.mock("../app/connectionState", () => ({
  getActiveConnectionId: () => null,
  getSelectedConnectionId: () => null,
  setActiveConnectionId: vi.fn(),
  setSelectedConnectionId: vi.fn(),
}));

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  return {
    ...actual,
    listClientConnections: vi.fn(async () => ({ ok: true, client_id: mocks.activeClientId, connections: [] })),
    listGenericConnections: vi.fn(async () => ({ ok: true, client_id: mocks.activeClientId, connections: [] })),
    getClientIntegrations: vi.fn(async () => {
      if (mocks.shouldRejectNext) {
        mocks.shouldRejectNext = false;
        throw new Error("network down");
      }
      return mocks.canonicalResponse;
    }),
    getApiVersion: vi.fn(async () => ({ commit_sha: "test-sha", build_time: "test", environment: "test" })),
  };
});

import Onboarding from "./Onboarding";
import { getClientIntegrations, listClientConnections, listGenericConnections } from "../app/api";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function renderOnboarding() {
  await act(async () => {
    root.render(<Onboarding isAuthenticated />);
  });
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
}

function canonicalConnection(overrides: Record<string, unknown> = {}) {
  return {
    provider: "meta",
    connection_id: "auth-meta-1",
    status: "connected",
    authorization_status: "valid",
    sync_status: "sync_success",
    account: { id: "act_1", name: "Amalie" },
    assets: { ad_account_id: "act_1", ad_account_name: "Amalie" },
    last_sync_at: "2026-08-05T20:10:20+00:00",
    last_successful_sync_at: "2026-08-05T20:10:20+00:00",
    last_error: null,
    updated_at: "2026-08-05T20:10:22+00:00",
    ...overrides,
  };
}

function findButton(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((item) => item.textContent === text);
}

// Botão adicionado nesta fase (contrato canônico) — distinto do botão
// legado "Atualizar status", que já existia e recarrega tudo.
const REFRESH_BUTTON_IDLE = "Verificar status";
const REFRESH_BUTTON_BUSY = "Verificando...";

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mocks.activeClientId = "amalie";
  mocks.canonicalResponse = { ok: true, client_id: "amalie", connections: [canonicalConnection()] };
  mocks.shouldRejectNext = false;
  vi.mocked(getClientIntegrations).mockClear();
  vi.mocked(listClientConnections).mockClear();
  vi.mocked(listGenericConnections).mockClear();
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(async () => {
  try {
    await act(async () => root.unmount());
  } catch {
    // Alguns testes desmontam explicitamente no meio do teste; unmount
    // duplo é seguro de ignorar aqui.
  }
  container.remove();
});

describe("Onboarding — contrato canônico de integrações", () => {
  it("mostra a conexão existente como conectada/sincronizada a partir do endpoint canônico", async () => {
    await renderOnboarding();
    expect(container.textContent).toContain("Sincronizado");
    expect(container.textContent).toContain("Conta: Amalie");
  });

  it("não existe mais o badge duplicado 'Status consolidado'", async () => {
    await renderOnboarding();
    expect(container.textContent).not.toContain("Status consolidado");
  });

  it("token_expired aparece corretamente no card", async () => {
    mocks.canonicalResponse = {
      ok: true,
      client_id: "amalie",
      connections: [canonicalConnection({ status: "token_expired", sync_status: null })],
    };
    await renderOnboarding();
    expect(container.textContent).toContain("Token expirado");
    expect(container.querySelector(".statusBadge.is-error")).toBeTruthy();
  });

  it("permission_error aparece corretamente no card", async () => {
    mocks.canonicalResponse = {
      ok: true,
      client_id: "amalie",
      connections: [canonicalConnection({ status: "permission_error", authorization_status: "invalid", sync_status: null })],
    };
    await renderOnboarding();
    expect(container.textContent).toContain("Permissão insuficiente");
  });

  it("erro de sincronização aparece sem apagar a conta selecionada", async () => {
    mocks.canonicalResponse = {
      ok: true,
      client_id: "amalie",
      connections: [canonicalConnection({ sync_status: "sync_error", last_error: "Meta retornou 500" })],
    };
    await renderOnboarding();
    expect(container.textContent).toContain("Erro de sincronização");
    expect(container.textContent).toContain("Conta: Amalie");
    expect(container.textContent).toContain("Meta retornou 500");
  });

  it("usa o client_id da empresa ativa, não um valor fixo", async () => {
    mocks.activeClientId = "roove";
    mocks.canonicalResponse = {
      ok: true,
      client_id: "roove",
      connections: [canonicalConnection({ account: { id: "act_9", name: "Roove" } })],
    };
    await renderOnboarding();
    expect(container.textContent).toContain("Conta: Roove");
    expect(container.textContent).not.toContain("Conta: Amalie");
  });

  it("erro de rede no refetch mantém o último estado e mostra aviso discreto", async () => {
    await renderOnboarding();
    expect(container.textContent).toContain("Conta: Amalie");

    mocks.shouldRejectNext = true;
    const button = findButton(REFRESH_BUTTON_IDLE);
    expect(button).toBeTruthy();
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());

    expect(container.textContent).toContain("Não foi possível atualizar agora. Exibindo o último estado salvo.");
    // Estado anterior continua visível, card não vira "desconectado".
    expect(container.textContent).toContain("Conta: Amalie");
    expect(container.textContent).toContain("Sincronizado");
  });

  it("sucesso posterior remove o aviso de erro", async () => {
    await renderOnboarding();
    mocks.shouldRejectNext = true;
    const button = findButton(REFRESH_BUTTON_IDLE);
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain("Não foi possível atualizar agora");

    await act(async () => {
      findButton(REFRESH_BUTTON_IDLE)?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());

    expect(container.textContent).not.toContain("Não foi possível atualizar agora");
  });

  it("botão 'Verificar status' chama somente o refetch canônico, sem OAuth/sincronização e sem recarregar endpoints legados", async () => {
    await renderOnboarding();
    const canonicalCallsBefore = vi.mocked(getClientIntegrations).mock.calls.length;
    const clientCallsBefore = vi.mocked(listClientConnections).mock.calls.length;
    const genericCallsBefore = vi.mocked(listGenericConnections).mock.calls.length;

    const button = findButton(REFRESH_BUTTON_IDLE);
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => Promise.resolve());

    expect(vi.mocked(getClientIntegrations).mock.calls.length).toBe(canonicalCallsBefore + 1);
    expect(vi.mocked(listClientConnections).mock.calls.length).toBe(clientCallsBefore);
    expect(vi.mocked(listGenericConnections).mock.calls.length).toBe(genericCallsBefore);
  });

  it("botão mostra estado de carregamento e mantém os cards visíveis durante a atualização", async () => {
    let resolveSecond: (value: unknown) => void = () => {};
    await renderOnboarding();
    vi.mocked(getClientIntegrations).mockImplementationOnce(
      () => new Promise((resolve) => { resolveSecond = resolve; }) as never
    );

    const button = findButton(REFRESH_BUTTON_IDLE);
    act(() => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => Promise.resolve());

    expect(findButton(REFRESH_BUTTON_BUSY)).toBeTruthy();
    // Cards continuam com o último dado válido, não somem durante o loading.
    expect(container.textContent).toContain("Conta: Amalie");

    await act(async () => {
      resolveSecond(mocks.canonicalResponse);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findButton(REFRESH_BUTTON_IDLE)).toBeTruthy();
  });

  it("estado canônico prevalece sobre o texto legado assim que a linha canônica existe", async () => {
    // O fluxo legado (genericConnections) está vazio neste teste — se ele
    // ainda decidisse o texto do card Meta, apareceria "Não conectado" ali.
    // Como o canônico já tem uma linha para "meta", ele prevalece.
    await renderOnboarding();
    const metaCard = [...container.querySelectorAll(".onboardingConnBlock")].find((block) =>
      block.textContent?.includes("Meta e Instagram")
    );
    expect(metaCard).toBeTruthy();
    expect(metaCard?.textContent).toContain("Sincronizado");
    expect(metaCard?.textContent).not.toContain("Não conectado");
  });
});

describe("Onboarding — mount/OAuth: estabilidade de efeitos", () => {
  it("re-render comum não chama de novo os endpoints legados nem entra em loop", async () => {
    await renderOnboarding();
    const clientCallsAfterMount = vi.mocked(listClientConnections).mock.calls.length;
    const genericCallsAfterMount = vi.mocked(listGenericConnections).mock.calls.length;
    expect(clientCallsAfterMount).toBe(1);
    expect(genericCallsAfterMount).toBe(1);

    // Provoca re-renders comuns (clique no botão canônico, que só atualiza
    // estado do hook canônico) e confirma que os endpoints legados de mount
    // não voltam a ser chamados por isso.
    const button = findButton(REFRESH_BUTTON_IDLE);
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());

    expect(vi.mocked(listClientConnections).mock.calls.length).toBe(clientCallsAfterMount);
    expect(vi.mocked(listGenericConnections).mock.calls.length).toBe(genericCallsAfterMount);
  });

  it("mudança real de client_id recarrega as conexões da nova empresa", async () => {
    await renderOnboarding();
    expect(vi.mocked(listClientConnections).mock.calls.length).toBe(1);

    mocks.activeClientId = "roove";
    mocks.canonicalResponse = { ok: true, client_id: "roove", connections: [] };
    await act(async () => {
      root.render(<Onboarding isAuthenticated />);
    });
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());

    expect(vi.mocked(listClientConnections).mock.calls.length).toBe(2);
  });

  it("desmontagem durante uma carga em andamento não tenta atualizar estado (sem warning de setState pós-unmount)", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let resolveClient: (value: unknown) => void = () => {};
    vi.mocked(listClientConnections).mockImplementationOnce(
      () => new Promise((resolve) => { resolveClient = resolve; }) as never
    );

    await act(async () => {
      root.render(<Onboarding isAuthenticated />);
    });
    await act(async () => Promise.resolve());

    await act(async () => {
      root.unmount();
    });

    // A Promise da carga em andamento só resolve DEPOIS da desmontagem.
    await act(async () => {
      resolveClient({ ok: true, client_id: "amalie", connections: [] });
      await Promise.resolve();
      await Promise.resolve();
    });

    const setStateWarning = errorSpy.mock.calls.some((call) =>
      String(call[0] || "").includes("unmounted")
    );
    expect(setStateWarning).toBe(false);
    errorSpy.mockRestore();
  });
});
