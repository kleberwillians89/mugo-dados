// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({
  getHistoryPlan: vi.fn(), requestHistory: vi.fn(), cancelHistory: vi.fn(), runHistoryRound: vi.fn(),
}));
vi.mock("../../app/api", () => api);

import HistoryBackfillPanel from "./HistoryBackfillPanel";

const COMPANIES = [{ id: "curavino", name: "Curavino LTDA", trade_name: "Curavino", status: "active" }];

const SIMULATION = {
  ok: true, client_id: "curavino", start: "2026-01-01", request: null,
  providers: [
    { provider: "fbits", label: "FBITS/Wake · pedidos", connected: true, earliest_in_database: "2026-07-29",
      missing_start: "2026-01-01", missing_end: "2026-07-28", blocks_total: 30, blocks_done: 0, state: "pending" },
    { provider: "shopify", label: "Shopify · pedidos", connected: false, blocks_total: 0, blocks_done: 0, state: "not_connected" },
  ],
};

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

const button = (label: string) =>
  Array.from(container.querySelectorAll("button")).find((item) => item.textContent === label) as HTMLButtonElement;

describe("HistoryBackfillPanel", () => {
  it("simula sem gravar e só agenda depois de confirmar", async () => {
    api.getHistoryPlan.mockResolvedValue(SIMULATION);
    api.requestHistory.mockResolvedValue({ ...SIMULATION, request: { id: "r1" } });
    act(() => root.render(<HistoryBackfillPanel companies={COMPANIES} />));
    await act(async () => {
      container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(api.getHistoryPlan).toHaveBeenCalledWith("curavino", "2026-01-01");
    const text = container.textContent || "";
    expect(text).toContain("01/01/2026 a 28/07/2026");
    expect(text).toContain("0 de 30 blocos");
    expect(text).toContain("Não conectado");
    expect(api.requestHistory).not.toHaveBeenCalled();

    await act(async () => button("Agendar busca").click());
    expect(api.requestHistory).not.toHaveBeenCalled();
    api.getHistoryPlan.mockResolvedValue({ ...SIMULATION, request: { id: "r1" } });
    await act(async () => button("Confirmar agendamento").click());
    expect(api.requestHistory).toHaveBeenCalledWith("curavino", "2026-01-01");
    expect(container.textContent).toContain("Rodar uma rodada agora");
  });
});
