// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useDashboardPaid from "./useDashboardPaid";
import { clearDashboardCacheByPrefix } from "./cache";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../app/api", () => ({
  getDashboardPaid: vi.fn(),
}));

import { getDashboardPaid } from "../../app/api";

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

function unmount() {
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
}

beforeEach(() => {
  clearDashboardCacheByPrefix("paid");
});

afterEach(() => {
  unmount();
  vi.clearAllMocks();
});

function Harness({
  clientId,
  connectionId,
  filters,
  onState,
}: {
  clientId: string;
  connectionId?: string;
  filters?: { campaign?: string; adset?: string; ad?: string; platform?: string };
  onState: (state: ReturnType<typeof useDashboardPaid>) => void;
}) {
  const state = useDashboardPaid({
    isAuthenticated: true,
    activeClientId: clientId,
    activeConnectionId: connectionId,
    period: { start: "2026-08-01", end: "2026-08-08" },
    filters,
  });
  onState(state);
  return null;
}

describe("useDashboardPaid — persistência real ao desmontar/remontar (troca de tela)", () => {
  it("filtros compostos fazem somente GET persistido com o mesmo período", async () => {
    vi.mocked(getDashboardPaid).mockResolvedValueOnce({ totals: { spend: 100 }, daily: [] } as never);
    await mount(
      <Harness
        clientId="amalie"
        connectionId="paid-1"
        filters={{ campaign: "Agosto", adset: "Mulheres", ad: "Video A", platform: "instagram" }}
        onState={() => {}}
      />
    );
    await act(async () => { await Promise.resolve(); });

    expect(getDashboardPaid).toHaveBeenCalledTimes(1);
    expect(getDashboardPaid).toHaveBeenCalledWith(
      { start: "2026-08-01", end: "2026-08-08" },
      expect.objectContaining({
        connectionId: "paid-1", campaign: "Agosto", adset: "Mulheres", ad: "Video A", platform: "instagram",
      })
    );
  });

  it("browser novo sem connection_id ainda faz GET para o backend resolver a conexão paid", async () => {
    const response = { connection_id: "paid-amalie", totals: { spend: 900 }, daily: [] };
    vi.mocked(getDashboardPaid).mockResolvedValueOnce(response as never);

    let latest: ReturnType<typeof useDashboardPaid> | null = null;
    await mount(<Harness clientId="amalie" onState={(state) => { latest = state; }} />);
    await act(async () => { await Promise.resolve(); });

    expect(getDashboardPaid).toHaveBeenCalledWith(
      { start: "2026-08-01", end: "2026-08-08" },
      expect.objectContaining({ connectionId: undefined })
    );
    expect(latest?.paidData).toEqual(response);
  });
  it("remontar com os mesmos parâmetros mostra o snapshot em cache imediatamente, sem esperar novo fetch", async () => {
    const firstResponse = { totals: { spend: 1294 }, daily: [] };
    const mocked = vi.mocked(getDashboardPaid);
    mocked.mockResolvedValueOnce(firstResponse as never);
    // A segunda chamada (remount) fica pendurada de propósito — o teste
    // precisa provar que o dado exibido vem do cache, não dessa promise.
    mocked.mockImplementationOnce(() => new Promise(() => {}) as never);

    let latest: ReturnType<typeof useDashboardPaid> | null = null;
    await mount(<Harness clientId="amalie" connectionId="conn-1" onState={(s) => { latest = s; }} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.paidData).toEqual(firstResponse);

    // Simula sair da tela (unmount) e voltar (remount) — como troca de rota.
    unmount();
    latest = null;
    await mount(<Harness clientId="amalie" connectionId="conn-1" onState={(s) => { latest = s; }} />);

    // Sem nenhum await adicional: o valor precisa estar disponível já no
    // primeiro render, vindo do cache — nunca null "por um frame".
    expect(latest?.paidData).toEqual(firstResponse);
    expect(latest?.loadingPaid).toBe(false);
  });

  it("cache é isolado por client_id — remontar com outro tenant nunca mostra o dado anterior", async () => {
    const amalieResponse = { totals: { spend: 1294 }, daily: [] };
    const mocked = vi.mocked(getDashboardPaid);
    mocked.mockResolvedValueOnce(amalieResponse as never);
    mocked.mockImplementationOnce(() => new Promise(() => {}) as never);

    let latest: ReturnType<typeof useDashboardPaid> | null = null;
    await mount(<Harness clientId="amalie" connectionId="conn-1" onState={(s) => { latest = s; }} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.paidData).toEqual(amalieResponse);

    unmount();
    latest = null;
    await mount(<Harness clientId="roove" connectionId="conn-roove" onState={(s) => { latest = s; }} />);
    expect(latest?.paidData).toBeNull();
    expect(latest?.paidData).not.toEqual(amalieResponse);
  });

  it("erro no refetch preserva o snapshot anterior — nunca zera o dado válido", async () => {
    const firstResponse = { totals: { spend: 1294 }, daily: [] };
    const mocked = vi.mocked(getDashboardPaid);
    mocked.mockResolvedValueOnce(firstResponse as never);

    let latest: ReturnType<typeof useDashboardPaid> | null = null;
    await mount(<Harness clientId="amalie" connectionId="conn-1" onState={(s) => { latest = s; }} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.paidData).toEqual(firstResponse);

    mocked.mockRejectedValueOnce(new Error("Meta indisponível"));
    await act(async () => {
      await latest?.reloadPaid({ force: true });
    });
    expect(latest?.paidData).toEqual(firstResponse);
    expect(latest?.paidError).toBe("Meta indisponível");
  });
});
