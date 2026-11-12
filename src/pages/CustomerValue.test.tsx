// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VALUE_FIXTURE } from "./customerValue.fixture";

const api = vi.hoisted(() => ({ getCustomerValue: vi.fn() }));
vi.mock("../app/api", async (orig) => ({ ...(await orig<object>()), ...api }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("recharts", async (orig) => ({ ...(await orig<object>()), ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
const CustomerValue = (await import("./CustomerValue")).default;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
describe("CRM → LTV e CAC", () => {
  beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); api.getCustomerValue.mockReset(); });
  afterEach(() => { act(() => root.unmount()); host.remove(); });

  it("mostra LTV:CAC, recompra e a tabela de coortes", async () => {
    api.getCustomerValue.mockResolvedValue(VALUE_FIXTURE);
    await act(async () => { root.render(<CustomerValue />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(host.textContent).toContain("5,12x");
    expect(host.textContent).toContain("saudável");
    expect(host.textContent).toContain("27,4%");
    expect(host.querySelectorAll(".cvCohorts tbody tr")).toHaveLength(12);
    expect(host.querySelector(".cvCohorts tbody th")?.textContent).toBe("nov/26");
  });

  it("sem pedidos explica que aparece sozinho", async () => {
    api.getCustomerValue.mockResolvedValue({ ok: true, status: "not_built" });
    await act(async () => { root.render(<CustomerValue />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(host.textContent).toContain("Ainda não há pedidos suficientes");
  });
});
