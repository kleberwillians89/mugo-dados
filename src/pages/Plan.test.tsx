// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ADMIN_FIXTURE, PLAN_FIXTURE } from "./plan.fixture";

const api = vi.hoisted(() => ({ getMyPlan: vi.fn(), getAdminPlans: vi.fn(), saveSubscription: vi.fn(), removeSubscription: vi.fn(), savePlan: vi.fn(), markInvoicePaid: vi.fn() }));
vi.mock("../app/saas", async (orig) => ({ ...(await orig<object>()), ...api }));
vi.mock("../app/activeClient", async (orig) => ({ ...(await orig<object>()), getActiveClientName: () => "Roove" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
const Plan = (await import("./Plan")).default;
const PlansAdmin = (await import("./PlansAdmin")).default;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("Planos", () => {
  beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); Object.values(api).forEach((f) => f.mockReset()); });
  afterEach(() => { act(() => root.unmount()); host.remove(); });

  it("empresa vê implantação, uso e faturas", async () => {
    api.getMyPlan.mockResolvedValue(PLAN_FIXTURE);
    await act(async () => { root.render(<Plan />); });
    await flush();
    expect(host.querySelector(".saProgress")?.textContent).toBe("6 de 9");
    expect(host.textContent).toContain("Plano Crescimento");
    expect(host.textContent).toContain("41.200 / 50.000");
    expect(host.querySelectorAll(".saSteps li:not(.is-done) button")).toHaveLength(3);
    expect(host.textContent).toContain("outubro de 2026");
  });

  it("sem plano diz que não há limite", async () => {
    api.getMyPlan.mockResolvedValue({ ...PLAN_FIXTURE, subscription: null, invoices: [], meters: PLAN_FIXTURE.meters.map((m) => ({ ...m, limit: null, remaining: null })) });
    await act(async () => { root.render(<Plan />); });
    await flush();
    expect(host.textContent).toContain("sem limites de uso");
  });

  it("admin troca o plano de uma empresa", async () => {
    api.getAdminPlans.mockResolvedValue(ADMIN_FIXTURE);
    api.saveSubscription.mockResolvedValue({});
    await act(async () => { root.render(<PlansAdmin />); });
    await flush();
    expect(host.textContent).toContain("1.494,00");
    expect(host.textContent).toContain("vencida");
    const select = host.querySelector<HTMLSelectElement>('[aria-label="Plano de Curavino"]')!;
    await act(async () => { select.value = "essencial"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(api.saveSubscription).toHaveBeenCalledWith("curavino", { plan_id: "essencial", status: "teste", trial_days: 14 });
  });
});
