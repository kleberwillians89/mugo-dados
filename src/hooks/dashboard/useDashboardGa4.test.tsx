// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useDashboardGa4 from "./useDashboardGa4";
import { clearDashboardCacheByPrefix } from "./cache";
import { getSelectedConnectionId, setSelectedConnectionId } from "../../app/connectionState";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../app/api", () => ({
  getGa4Report: vi.fn(),
  listGenericConnections: vi.fn(),
}));

import { getGa4Report, listGenericConnections } from "../../app/api";

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
  clearDashboardCacheByPrefix("ga4");
  window.localStorage.removeItem("mugo_dados.selected_connections");
  vi.mocked(listGenericConnections).mockResolvedValue({ ok: true, client_id: "amalie", connections: [] });
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

function Harness({
  clientId,
  onState,
}: {
  clientId: string;
  onState: (state: ReturnType<typeof useDashboardGa4>) => void;
}) {
  const state = useDashboardGa4({
    isAuthenticated: true,
    activeClientId: clientId,
    period: { start: "2026-08-01", end: "2026-08-05" },
  });
  onState(state);
  return null;
}

describe("useDashboardGa4 — isolamento entre tenants", () => {
  it("resposta lenta da Amalie chegando depois da troca para Roove nunca sobrescreve a Roove", async () => {
    const amalieReport = { meta: {}, daily: [{ date: "2026-08-01", sessions: 111 }] };
    let resolveAmalie: (value: unknown) => void = () => {};
    const rooveReport = { meta: {}, daily: [{ date: "2026-08-01", sessions: 222 }] };

    const mocked = vi.mocked(getGa4Report);
    mocked.mockImplementationOnce(() => new Promise((resolve) => { resolveAmalie = resolve; }) as never);
    mocked.mockResolvedValueOnce(rooveReport as never);

    let latest: ReturnType<typeof useDashboardGa4> | null = null;
    await mount(<Harness clientId="amalie" onState={(s) => { latest = s; }} />);

    // Amalie ainda está carregando (nunca resolveu). Troca para Roove antes
    // da resposta da Amalie chegar.
    await act(async () => {
      root!.render(<Harness clientId="roove" onState={(s) => { latest = s; }} />);
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.ga4Report).toEqual(rooveReport);

    // A resposta atrasada da Amalie chega DEPOIS — não pode sobrescrever a Roove.
    await act(async () => {
      resolveAmalie(amalieReport);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.ga4Report).toEqual(rooveReport);
    expect(latest?.ga4Report).not.toEqual(amalieReport);
  });

  it("troca de tenant sem cache para o novo cliente limpa o relatório do tenant anterior (não fica preso indefinidamente)", async () => {
    const amalieReport = { meta: {}, daily: [{ date: "2026-08-01", sessions: 111 }] };
    const mocked = vi.mocked(getGa4Report);
    mocked.mockResolvedValueOnce(amalieReport as never);
    mocked.mockImplementationOnce(() => new Promise(() => {}) as never); // Roove nunca resolve neste teste

    let latest: ReturnType<typeof useDashboardGa4> | null = null;
    await mount(<Harness clientId="amalie" onState={(s) => { latest = s; }} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.ga4Report).toEqual(amalieReport);

    await act(async () => {
      root!.render(<Harness clientId="roove" onState={(s) => { latest = s; }} />);
    });

    // Sem esperar a busca da Roove terminar: o relatório da Amalie já não
    // pode estar visível — nem por um frame, nem indefinidamente.
    expect(latest?.ga4Report).toBeNull();
  });

  it("cache é separado por client_id — voltar para um tenant já visitado não mostra o outro", async () => {
    const amalieReport = { meta: {}, daily: [{ date: "2026-08-01", sessions: 111 }] };
    const rooveReport = { meta: {}, daily: [{ date: "2026-08-01", sessions: 222 }] };
    const mocked = vi.mocked(getGa4Report);
    mocked.mockResolvedValueOnce(amalieReport as never);
    mocked.mockResolvedValueOnce(rooveReport as never);
    // Terceira chamada (voltar para Amalie) fica pendurada de propósito —
    // este teste valida o valor lido do CACHE local, não uma nova busca.
    mocked.mockImplementationOnce(() => new Promise(() => {}) as never);

    let latest: ReturnType<typeof useDashboardGa4> | null = null;
    await mount(<Harness clientId="amalie" onState={(s) => { latest = s; }} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.ga4Report).toEqual(amalieReport);

    await act(async () => {
      root!.render(<Harness clientId="roove" onState={(s) => { latest = s; }} />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(latest?.ga4Report).toEqual(rooveReport);

    await act(async () => {
      root!.render(<Harness clientId="amalie" onState={(s) => { latest = s; }} />);
    });
    expect(latest?.ga4Report).toEqual(amalieReport);
    expect(latest?.ga4Report).not.toEqual(rooveReport);
  });
});

describe("useDashboardGa4 — evita 409 CONNECTION_SELECTION_REQUIRED quando há exatamente uma conexão GA4", () => {
  it("sem ponteiro local e com uma única conexão GA4 ativa, persiste o connection_id antes de ler o relatório", async () => {
    vi.mocked(listGenericConnections).mockResolvedValue({
      ok: true,
      client_id: "amalie",
      connections: [
        { id: "ga4-conn-1", client_id: "amalie", provider: "ga4", status: "connected" } as never,
        { id: "meta-conn-1", client_id: "amalie", provider: "meta", status: "connected" } as never,
      ],
    });
    const mocked = vi.mocked(getGa4Report);
    mocked.mockResolvedValueOnce({ meta: {}, daily: [] } as never);

    expect(getSelectedConnectionId("amalie", "ga4")).toBeNull();
    await mount(<Harness clientId="amalie" onState={() => {}} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getSelectedConnectionId("amalie", "ga4")).toBe("ga4-conn-1");
    expect(mocked).toHaveBeenCalledTimes(1);
  });

  it("com duas conexões GA4 ativas, nunca escolhe sozinho — ambiguidade real continua exigindo seleção explícita", async () => {
    vi.mocked(listGenericConnections).mockResolvedValue({
      ok: true,
      client_id: "amalie",
      connections: [
        { id: "ga4-conn-1", client_id: "amalie", provider: "ga4", status: "connected" } as never,
        { id: "ga4-conn-2", client_id: "amalie", provider: "ga4", status: "connected" } as never,
      ],
    });
    const mocked = vi.mocked(getGa4Report);
    mocked.mockResolvedValueOnce({ meta: {}, daily: [] } as never);

    await mount(<Harness clientId="amalie" onState={() => {}} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getSelectedConnectionId("amalie", "ga4")).toBeNull();
  });

  it("ponteiro já persistido localmente não é sobrescrito nem relista conexões", async () => {
    setSelectedConnectionId("amalie", "ga4", "ga4-existing");
    const mocked = vi.mocked(getGa4Report);
    mocked.mockResolvedValueOnce({ meta: {}, daily: [] } as never);

    await mount(<Harness clientId="amalie" onState={() => {}} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getSelectedConnectionId("amalie", "ga4")).toBe("ga4-existing");
    expect(listGenericConnections).not.toHaveBeenCalled();
  });
});
