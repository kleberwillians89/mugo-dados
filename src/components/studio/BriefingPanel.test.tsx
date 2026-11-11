// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const crm = vi.hoisted(() => ({ listAssignees: vi.fn(async () => ({ available: true, people: [{ user_id: "u-liliu", name: "Liliu" }] })) }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...crm }));
const studio = vi.hoisted(() => ({ sendBriefing: vi.fn(async () => ({ task: { id: "t1", title: "Designer: x" } })), generateBriefing: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));

import BriefingPanel from "./BriefingPanel";

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;

describe("Enviar o briefing para alguém", () => {
  it("escolhe a função e a pessoa e vira tarefa dela", async () => {
    const item = { id: "i1", title: "3 perfumes", visual_idea: "Frascos", signals: { briefing: { objective: "Pedidos de decant" } } } as never;
    await act(async () => { root.render(<BriefingPanel item={item} />); });
    await act(async () => { btn("Enviar para…").click(); });
    await act(async () => {});
    const selects = host.querySelectorAll(".briefingSend select");
    const person = selects[1] as HTMLSelectElement;
    expect(btn("Enviar briefing").disabled).toBe(true);  // tem integrantes: precisa escolher
    await act(async () => { person.value = "u-liliu"; person.dispatchEvent(new Event("change", { bubbles: true })); });
    await act(async () => { btn("Enviar briefing").click(); });
    expect(studio.sendBriefing).toHaveBeenCalledWith("i1", { role: "designer", assignee_user_id: "u-liliu", assignee_name: "Liliu", due_date: null, note: null });
    expect(host.textContent).toContain("Enviado para Liliu (Designer)");
  });
});
