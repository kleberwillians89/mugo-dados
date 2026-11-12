// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({
  getAdminPlans: vi.fn(), getCommercialCatalog: vi.fn(),
  getCommercialConfig: vi.fn(), saveCommercialConfig: vi.fn(),
  removeSubscription: vi.fn(), savePlan: vi.fn(), saveSubscription: vi.fn(),
}));
vi.mock("../app/saas", () => ({
  ...api,
  brl: (value: number) => `R$ ${(value / 100).toFixed(2)}`,
  STATUS_LABEL: { teste: "Em teste" },
}));
vi.mock("../components/Shell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <main>{children}</main>,
}));
vi.mock("../components/data/PageHeader", () => ({
  default: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

import PlansAdmin from "./PlansAdmin";

const tenants = [
  { client_id: "tenant-a", name: "Tenant A", subscription: null, plan_name: null, mrr_cents: 0, open_cents: 0, overdue: false },
  { client_id: "tenant-b", name: "Tenant B", subscription: null, plan_name: null, mrr_cents: 0, open_cents: 0, overdue: false },
];
const options = [
  { key: "meta", label: "Meta" },
  { key: "google", label: "Google" },
  { key: "social_media", label: "Social Media" },
];
const state = (client_id: string, module_keys: string[] | null, version: number | null) => ({
  client_id, module_keys, version, configured: version !== null,
  state: version === null ? "not_configured" : module_keys?.length ? "selected" : "explicitly_empty",
  updated_at: null, basic_capabilities: ["briefing", "tasks"],
});

let target: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  Object.values(api).forEach(fn => fn.mockReset());
  api.getAdminPlans.mockResolvedValue({ companies: tenants, plans: [], mrr_cents: 0 });
  api.getCommercialCatalog.mockResolvedValue({ modules: options, basic_capabilities: ["briefing", "tasks"], enforcement_enabled: false });
  api.getCommercialConfig.mockImplementation(async (clientId: string) => ({
    configuration: clientId === "tenant-a" ? state(clientId, null, null) : state(clientId, ["google"], 4),
  }));
  api.saveCommercialConfig.mockImplementation(async (clientId: string, keys: string[], version: number | null) => ({
    configuration: state(clientId, keys, (version ?? 0) + 1),
  }));
  target = document.createElement("div");
  document.body.appendChild(target);
  root = createRoot(target);
});

afterEach(async () => {
  await act(async () => root.unmount());
  target.remove();
});

async function render() {
  await act(async () => root.render(<PlansAdmin />));
  await flush();
}
async function flush() {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}
function button(text: string): HTMLButtonElement {
  const result = [...target.querySelectorAll("button")].find(x => x.textContent === text);
  if (!result) throw new Error(`Missing button: ${text}`);
  return result as HTMLButtonElement;
}
async function click(el: HTMLElement) {
  await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
  await flush();
}
function choice(label: string): HTMLInputElement {
  const parent = [...target.querySelectorAll(".saModuleChoice")].find(x => x.textContent?.includes(label));
  const el = parent?.querySelector("input");
  if (!el) throw new Error(`Missing module choice: ${label}`);
  return el;
}
async function toggle(label: string) {
  await act(async () => { choice(label).dispatchEvent(new MouseEvent("click", { bubbles: true })); });
}

describe("Commercial admin UI — mocked HTTP boundary", () => {
  it("saves explicit empty on tenant A and reloads state without confusing it with missing", async () => {
    await render();
    await click(button("Módulos"));
    expect(target.textContent).toContain("Ainda não configurado");
    expect(button("Salvar módulos").disabled).toBe(false);
    await click(button("Salvar módulos"));
    expect(api.saveCommercialConfig).toHaveBeenCalledWith("tenant-a", [], null);
    expect(target.textContent).toContain("Nenhum módulo opcional contratado");
    expect(button("Salvar módulos").disabled).toBe(true);
    await click(button("Recarregar"));
    expect(api.getCommercialConfig).toHaveBeenCalledWith("tenant-a");
  });

  it("switches tenants A → B → A without leaking checkboxes", async () => {
    await render();
    const buttons = [...target.querySelectorAll("button")].filter(x => x.textContent === "Módulos");
    await click(buttons[0]);
    expect(choice("Google").checked).toBe(false);
    await toggle("Meta");
    expect(choice("Meta").checked).toBe(true);
    await click(buttons[1]);
    expect(choice("Google").checked).toBe(true);
    expect(choice("Meta").checked).toBe(false);
    await click(buttons[0]);
    expect(choice("Google").checked).toBe(false);
    expect(choice("Meta").checked).toBe(false);
    expect(api.saveCommercialConfig).not.toHaveBeenCalled();
  });

  it("shows conflict, prevents blind retry, allows reload and then saving", async () => {
    await render();
    await click(button("Módulos"));
    await toggle("Meta");
    api.saveCommercialConfig.mockRejectedValueOnce(new Error("commercial_config_conflict"));
    await click(button("Salvar módulos"));
    expect(target.textContent).toContain("Recarregue antes de tentar novamente");
    expect(button("Salvar módulos").disabled).toBe(true);
    await click(button("Recarregar"));
    expect(button("Salvar módulos").disabled).toBe(false);
    await click(button("Salvar módulos"));
    expect(api.saveCommercialConfig).toHaveBeenLastCalledWith("tenant-a", ["meta"], null);
  });

  it("shows a read error and retry action without treating it as empty", async () => {
    api.getCommercialConfig.mockRejectedValueOnce(new Error("service unavailable"));
    await render();
    await click(button("Módulos"));
    expect(target.textContent).toContain("Configuração indisponível");
    expect(target.textContent).not.toContain("Nenhum módulo opcional contratado");
    await click(button("Tentar novamente"));
    expect(target.textContent).toContain("Ainda não configurado");
  });
});
