// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({
  getFbitsOrdersSummary: vi.fn(),
  getFbitsOrders: vi.fn(),
  getShopifyReport: vi.fn(),
  listGenericConnections: vi.fn(),
}));
vi.mock("../../app/api", () => api);

import useDashboardFbits from "./useDashboardFbits";

function Harness({ clientId, start, end }: { clientId: string; start: string; end: string }) {
  const report = useDashboardFbits({
    isAuthenticated: true,
    activeClientId: clientId,
    period: { start, end },
    provider: "fbits",
  });
  return <div data-testid="result">{report.loadingFbits ? "loading" : report.fbitsData?.summary.pedidos ?? "empty"}</div>;
}

const summary = (clientId: string, start: string, end: string, pedidos: number) => ({
  ok: true,
  connected: true,
  client_id: clientId,
  period: { start, end },
  summary: { receita_oficial: pedidos * 100, pedidos, ticket_medio: 100, clientes: pedidos, produtos_vendidos: pedidos },
});

describe("useDashboardFbits", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    window.sessionStorage.clear();
    Object.values(api).forEach((fn) => fn.mockReset());
    api.getFbitsOrdersSummary.mockImplementation(async ({ start, end }: { start: string; end: string }) =>
      summary("vinhos", start, end, start === "2026-09-24" ? 7 : 30)
    );
    api.getFbitsOrders.mockImplementation(async ({ start, end }: { start: string; end: string }) => ({
      ok: true, connected: true, client_id: "vinhos", period: { start, end }, count: 0, items: [],
    }));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    window.sessionStorage.clear();
  });

  async function render(clientId: string, start: string, end: string) {
    await act(async () => {
      root.render(<Harness clientId={clientId} start={start} end={end} />);
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("troca 30 para 7 dias, faz nova request e substitui os números", async () => {
    await render("vinhos", "2026-09-01", "2026-09-30");
    expect(container.textContent).toBe("30");
    await render("vinhos", "2026-09-24", "2026-09-30");
    expect(api.getFbitsOrdersSummary).toHaveBeenLastCalledWith({ start: "2026-09-24", end: "2026-09-30" });
    expect(container.textContent).toBe("7");
  });

  it("trocar tenant não reutiliza a cache do tenant anterior", async () => {
    api.getFbitsOrders.mockImplementation(async () => ({ok:true, client_id:api.getFbitsOrders.mock.calls.length===1 ? "vinhos" : "empresa-b", items:[]}));
    api.getFbitsOrdersSummary.mockImplementation(async ({ start, end }: { start: string; end: string }) => {
      const clientId = api.getFbitsOrdersSummary.mock.calls.length === 1 ? "vinhos" : "empresa-b";
      return summary(clientId, start, end, clientId === "vinhos" ? 12 : 3);
    });
    await render("vinhos", "2026-09-01", "2026-09-30");
    expect(container.textContent).toBe("12");
    await render("empresa-b", "2026-09-01", "2026-09-30");
    expect(container.textContent).toBe("3");
    expect(api.getFbitsOrdersSummary).toHaveBeenCalledTimes(2);
  });
});
