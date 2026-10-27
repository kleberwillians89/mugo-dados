// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ previewTestOrders: vi.fn(), cleanupTestOrders: vi.fn() }));
vi.mock("../../app/api", () => api);

import TestOrdersPanel from "./TestOrdersPanel";

const COMPANIES = [{ id: "roove", name: "Roove", status: "active" }];
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

describe("TestOrdersPanel", () => {
  it("procura, só remove após confirmar e informa o resultado", async () => {
    api.previewTestOrders.mockResolvedValue({ ok: true, client_id: "roove", dry_run: true, shopify_test_orders: 3, fbits_test_orders: 0, days: ["2026-10-20", "2026-10-21"] });
    api.cleanupTestOrders.mockResolvedValue({ ok: true, client_id: "roove", dry_run: false, shopify_test_orders: 3, fbits_test_orders: 0, days: [] });
    act(() => root.render(<TestOrdersPanel companies={COMPANIES} />));
    await act(async () => button("Procurar pedidos de teste").click());
    expect(container.textContent).toContain("3 pedido(s) de teste encontrados");
    await act(async () => button("Remover do painel").click());
    expect(api.cleanupTestOrders).not.toHaveBeenCalled();
    await act(async () => button("Confirmar remoção").click());
    expect(api.cleanupTestOrders).toHaveBeenCalledWith("roove");
    expect(container.textContent).toContain("3 pedido(s) de teste removido(s)");
  });
});
