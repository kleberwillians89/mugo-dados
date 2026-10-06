// @vitest-environment jsdom
import { buildDashboardCacheKey, writeDashboardCache, clearDashboardCacheByPrefix } from "./cache";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Regressão do caso Nasser (viewer de Curavino, 2026-10).
 *
 * A resolução da loja ativa lia `/api/clients/{id}/integrations`, que é
 * administrativo e responde 403 para viewer por decisão de produto. A página
 * de Ecommerce faz early return no erro, então o viewer via "Não foi possível
 * verificar as integrações" em vez do faturamento da própria empresa.
 *
 * A fonte passou a ser `/api/connections`, que qualquer membro lê.
 */

const api = vi.hoisted(() => ({
  listGenericConnections: vi.fn(),
  getClientIntegrations: vi.fn(),
}));
vi.mock("../../app/api", () => api);

const useActiveEcommerceProvider = (await import("./useActiveEcommerceProvider")).default;

const CURAVINO = "curavino";

type HookState = ReturnType<typeof useActiveEcommerceProvider>;

/** O estado do hook é publicado no DOM e lido de lá, sem mutar nada fora do
 * componente — é como os outros testes de hook deste projeto observam. */
function Harness({ clientId }: { clientId: string }) {
  const state = useActiveEcommerceProvider(clientId);
  return <script data-testid="state" type="application/json">{JSON.stringify(state)}</script>;
}

function observed(): HookState {
  const node = container.querySelector('[data-testid="state"]');
  if (!node) throw new Error("harness não renderizou o estado");
  return JSON.parse(node.textContent || "{}") as HookState;
}

function connection(overrides: Record<string, unknown> = {}) {
  return {
    id: "conn-fbits-1",
    client_id: CURAVINO,
    provider: "fbits",
    status: "connected",
    last_sync_at: "2026-10-04T09:00:00Z",
    last_error: null,
    account_id: "loja-1",
    account_name: "Curavino",
    ...overrides,
  };
}

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function render(clientId = CURAVINO) {
  await act(async () => {
    root.render(<Harness clientId={clientId} />);
  });
}

beforeEach(() => {
  clearDashboardCacheByPrefix("commerce-connections");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.listGenericConnections.mockReset();
  api.getClientIntegrations.mockReset();
  api.listGenericConnections.mockResolvedValue({
    ok: true,
    client_id: CURAVINO,
    connections: [connection()],
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("resolução da loja ativa para um viewer", () => {
  it("lê o endpoint que qualquer membro da empresa acessa", async () => {
    await render();
    expect(api.listGenericConnections).toHaveBeenCalledTimes(1);
  });

  it("nunca chama o endpoint administrativo de integrações", async () => {
    // Era a causa do 403: um viewer não lê o contrato técnico.
    await render();
    expect(api.getClientIntegrations).not.toHaveBeenCalled();
  });

  it("entrega a loja conectada sem erro", async () => {
    await render();
    expect(observed().loading).toBe(false);
    expect(observed().error).toBeNull();
    expect(observed().connections).toHaveLength(1);
    expect(observed().connections?.[0].provider).toBe("fbits");
    expect(observed().connections?.[0].status).toBe("connected");
  });

  it("preserva os campos que a página de Ecommerce consome", async () => {
    await render();
    const entry = observed().connections?.[0];
    expect(entry?.last_sync_at).toBe("2026-10-04T09:00:00Z");
    expect(entry?.last_error).toBeNull();
    expect(entry?.connection_id).toBe("conn-fbits-1");
  });

  it("reconhece a loja Shopify do mesmo jeito", async () => {
    api.listGenericConnections.mockResolvedValue({
      ok: true,
      client_id: CURAVINO,
      connections: [connection({ id: "conn-shopify-1", provider: "shopify" })],
    });
    await render();
    expect(observed().error).toBeNull();
    expect(observed().connections?.[0].provider).toBe("shopify");
  });

  it("não expõe conexões de outro tenant", async () => {
    api.listGenericConnections.mockResolvedValue({
      ok: true,
      client_id: "roove",
      connections: [connection({ client_id: "roove" })],
    });
    await render();
    expect(observed().connections).toBeNull();
    expect(observed().error).toBeTruthy();
  });

  it("empresa sem loja conectada não vira erro", async () => {
    api.listGenericConnections.mockResolvedValue({
      ok: true,
      client_id: CURAVINO,
      connections: [],
    });
    await render();
    expect(observed().error).toBeNull();
    expect(observed().connections).toEqual([]);
  });

  it("falha real da API continua sendo reportada", async () => {
    api.listGenericConnections.mockRejectedValue(new Error("Serviço indisponível."));
    await render();
    expect(observed().loading).toBe(false);
    expect(observed().error).toBe("Serviço indisponível.");
  });
});


it("cache existente libera a loja imediatamente enquanto revalidação permanece pendente", async () => {
  writeDashboardCache(buildDashboardCacheKey("commerce-connections", {clientId: CURAVINO}), [{provider:"fbits", connection_id:"cached", status:"connected"}]);
  let finish!: (value: unknown) => void;
  api.listGenericConnections.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await render();
  expect(observed().loading).toBe(false);
  expect(observed().connections?.[0].connection_id).toBe("cached");
  await act(async () => finish({client_id:CURAVINO,connections:[connection()]}));
  expect(observed().connections?.[0].connection_id).toBe("conn-fbits-1");
});
