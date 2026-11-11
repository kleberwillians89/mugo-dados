// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const crm = vi.hoisted(() => ({ listClientTasks: vi.fn() }));
vi.mock("../../app/crm", async (original) => ({ ...(await original<typeof import("../../app/crm")>()), ...crm }));
const studio = vi.hoisted(() => ({ getPipeline: vi.fn(), updateCalendarItem: vi.fn(),
  listItemReferences: vi.fn(async () => ({ references: [] })), listItemComments: vi.fn(async () => ({ comments: [] })) }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));

import ClientTasks from "./ClientTasks";

const post = (id: string, stage: string, status: string) => ({ id, title: `Post ${id}`, format: "reels", scheduled_at: "2026-11-27T22:00:00Z", status, stage,
  caption_draft: "Legenda", art_url: null, hook: null, request: null, client_feedback: null });

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

describe("Tarefas do cliente ligadas ao Calendário", () => {
  it("posts para aprovar entram no quadro e o cliente aprova pela tela do celular", async () => {
    crm.listClientTasks.mockResolvedValue({ available: true, tasks: [] });
    studio.getPipeline.mockImplementation(async (month: string) => ({ items: month.endsWith(String(new Date().getMonth() + 1).padStart(2, "0"))
      ? [post("a", "com_cliente", "em_revisao"), post("b", "aprovado", "aprovado")] : [] }));
    studio.updateCalendarItem.mockResolvedValue({ item: {} });
    await act(async () => { root.render(<ClientTasks isAgency={false} clientId="ruah" standalone />); });
    const col = (name: string) => [...host.querySelectorAll(".kanbanCol")].find((c) => c.querySelector("header b")?.textContent === name)!;
    expect(col("Aprovação do cliente").textContent).toContain("Post a");
    expect(col("Aprovada / concluída").textContent).toContain("Post b");
    expect(host.textContent).toContain("1 post esperando a sua aprovação.");
    const open = [...host.querySelectorAll("button")].find((b) => b.textContent === "Aprovar / ajuste") as HTMLButtonElement;
    await act(async () => { open.click(); });
    expect(host.querySelector(".phoneFrame")).toBeTruthy();
    const approve = [...host.querySelectorAll(".postReviewActions button")].find((b) => b.textContent === "Aprovar") as HTMLButtonElement;
    await act(async () => { approve.click(); });
    expect(studio.updateCalendarItem).toHaveBeenCalledWith("a", { status: "aprovado" });
    expect(host.textContent).toContain("Post aprovado. Obrigado!");
  });
});
