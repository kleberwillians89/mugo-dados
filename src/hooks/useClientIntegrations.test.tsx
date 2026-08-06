// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useClientIntegrations from "./useClientIntegrations";
import { clearDashboardCacheByPrefix } from "./dashboard/cache";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../app/api", () => ({
  getClientIntegrations: vi.fn(),
}));

const activeClientMocks = vi.hoisted(() => ({ clientId: "amalie" }));
vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => activeClientMocks.clientId,
}));

import { getClientIntegrations } from "../app/api";

let container: HTMLDivElement | null = null;
let root: Root | null = null;

async function mount(node: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(node);
  });
}

beforeEach(() => {
  activeClientMocks.clientId = "amalie";
  clearDashboardCacheByPrefix("client-integrations");
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
  vi.clearAllMocks();
});

function Harness({ onState }: { onState: (state: ReturnType<typeof useClientIntegrations>) => void }) {
  const state = useClientIntegrations({ enabled: true });
  onState(state);
  return null;
}

describe("useClientIntegrations", () => {
  it("keeps the last valid connections during a refetch instead of clearing to empty", async () => {
    const firstResponse = {
      ok: true,
      client_id: "amalie",
      connections: [{ provider: "meta", connection_id: "c1", status: "connected" }],
    };
    let resolveSecond: (value: unknown) => void = () => {};
    const mocked = vi.mocked(getClientIntegrations);
    mocked
      .mockResolvedValueOnce(firstResponse as never)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }) as never);

    let latest: ReturnType<typeof useClientIntegrations> | null = null;
    await mount(<Harness onState={(s) => { latest = s; }} />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.lastValidConnections).toHaveLength(1);

    // Dispara o refetch SEM aguardar — a Promise mockada da segunda chamada
    // só resolve quando `resolveSecond` for chamado explicitamente abaixo.
    act(() => {
      void latest!.refetch();
    });
    await act(async () => {
      await Promise.resolve();
    });
    // Segunda chamada ainda não resolveu (in-flight) — dado anterior deve
    // continuar visível, nunca substituído por array vazio.
    expect(latest?.lastValidConnections).toHaveLength(1);
    expect(latest?.isRefreshing).toBe(true);

    await act(async () => {
      resolveSecond({
        ok: true,
        client_id: "amalie",
        connections: [
          { provider: "meta", connection_id: "c1", status: "connected" },
          { provider: "ga4", connection_id: "c2", status: "connected" },
        ],
      });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.lastValidConnections).toHaveLength(2);
  });

  it("does not clear connections when a refetch fails", async () => {
    const firstResponse = {
      ok: true,
      client_id: "amalie",
      connections: [{ provider: "meta", connection_id: "c1", status: "connected" }],
    };
    const mocked = vi.mocked(getClientIntegrations);
    mocked.mockResolvedValueOnce(firstResponse as never).mockRejectedValueOnce(new Error("network down"));

    let latest: ReturnType<typeof useClientIntegrations> | null = null;
    await mount(<Harness onState={(s) => { latest = s; }} />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.lastValidConnections).toHaveLength(1);

    await act(async () => {
      await latest!.refetch();
    });

    expect(latest?.lastValidConnections).toHaveLength(1);
    expect(latest?.error).toBe("network down");
  });

  it("nunca mostra as conexões do tenant anterior ao trocar de empresa sem desmontar", async () => {
    const amalieResponse = {
      ok: true,
      client_id: "amalie",
      connections: [{ provider: "meta", connection_id: "amalie-meta", status: "connected" }],
    };
    let resolveRoove: (value: unknown) => void = () => {};
    const mocked = vi.mocked(getClientIntegrations);
    mocked
      .mockResolvedValueOnce(amalieResponse as never)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRoove = resolve; }) as never);

    let latest: ReturnType<typeof useClientIntegrations> | null = null;
    await mount(<Harness onState={(s) => { latest = s; }} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.lastValidConnections?.[0]?.connection_id).toBe("amalie-meta");

    // Troca de empresa sem desmontar o componente (mesma árvore, App
    // apenas re-renderiza com o novo client_id ativo).
    activeClientMocks.clientId = "roove";
    await act(async () => {
      root!.render(<Harness onState={(s) => { latest = s; }} />);
    });

    // Mesmo com a busca da Roove ainda em voo (nunca resolvida ainda), o
    // dado da Amalie já não pode aparecer — isolamento entre tenants não
    // pode depender do fetch terminar.
    expect(
      (latest?.lastValidConnections || []).some((item) => item.connection_id === "amalie-meta")
    ).toBe(false);

    await act(async () => {
      resolveRoove({
        ok: true,
        client_id: "roove",
        connections: [{ provider: "meta", connection_id: "roove-meta", status: "connected" }],
      });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.lastValidConnections?.[0]?.connection_id).toBe("roove-meta");
    expect(
      (latest?.lastValidConnections || []).some((item) => item.connection_id === "amalie-meta")
    ).toBe(false);
  });

  it("usa cache separado por client_id — voltar para um tenant já visitado não mostra o outro", async () => {
    const mocked = vi.mocked(getClientIntegrations);
    mocked.mockResolvedValueOnce({
      ok: true,
      client_id: "amalie",
      connections: [{ provider: "meta", connection_id: "amalie-meta", status: "connected" }],
    } as never);

    let latest: ReturnType<typeof useClientIntegrations> | null = null;
    await mount(<Harness onState={(s) => { latest = s; }} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.lastValidConnections?.[0]?.connection_id).toBe("amalie-meta");

    activeClientMocks.clientId = "roove";
    mocked.mockResolvedValueOnce({
      ok: true,
      client_id: "roove",
      connections: [{ provider: "meta", connection_id: "roove-meta", status: "connected" }],
    } as never);
    await act(async () => {
      root!.render(<Harness onState={(s) => { latest = s; }} />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.lastValidConnections?.[0]?.connection_id).toBe("roove-meta");

    // Volta para a Amalie: o cache local (por client_id) reaparece de
    // imediato — sem mostrar a Roove nem um instante sequer.
    activeClientMocks.clientId = "amalie";
    await act(async () => {
      root!.render(<Harness onState={(s) => { latest = s; }} />);
    });
    expect(
      (latest?.lastValidConnections || []).some((item) => item.connection_id === "roove-meta")
    ).toBe(false);
    expect(latest?.lastValidConnections?.[0]?.connection_id).toBe("amalie-meta");
  });
});
