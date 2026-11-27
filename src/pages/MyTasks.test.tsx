// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listMyTasks: vi.fn() }));
vi.mock("../app/myTasks", async (original) => ({ ...(await original<typeof import("../app/myTasks")>()), ...api }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title, controls }: { title: string; controls?: React.ReactNode }) => <header><h1>{title}</h1>{controls}</header> }));

import MyTasks from "./MyTasks";
import MyTasksButton from "../components/shell/MyTasksButton";
import { groupMyTasks, type MyTask } from "../app/myTasks";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const task = (id: string, extra: Partial<MyTask> = {}): MyTask => ({ id, title: `Tarefa ${id}`, status: "pending", priority: null, due_date: null,
  due_time: null, starts_at: null, category: "Design", task_type: null, tags: [], notes: null, updated_at: null, assignee: null,
  client_id: "roove", client_name: "Roove", ...extra });
const ok = (tasks: MyTask[]) => ({ ok: true as const, tasks, truncated: false,
  clients: [{ client_id: "roove", name: "Roove" }, { client_id: "ruah", name: "Ruah" }] });

let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); vi.useFakeTimers({ shouldAdvanceTime: true }); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); vi.useRealTimers(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };

describe("Minhas Tarefas (spec do Danilo, PR 2)", () => {
  it("agrupa por prazo: atrasadas, hoje, próximas e sem prazo", () => {
    const today = new Date(2026, 10, 25, 15);
    const g = groupMyTasks([task("a", { due_date: "2026-11-30" }), task("b", { due_date: "2026-11-24" }), task("c", { due_date: "2026-11-25" }),
      task("d"), task("e", { due_date: "2026-11-26" })], today);
    expect(g.late.map((t) => t.id)).toEqual(["b"]);
    expect(g.today.map((t) => t.id)).toEqual(["c"]);
    expect(g.next.map((t) => t.id)).toEqual(["e", "a"]);
    expect(g.none.map((t) => t.id)).toEqual(["d"]);
  });

  it("lista com empresa, área, status e prioridade e abre na empresa certa", async () => {
    api.listMyTasks.mockResolvedValue(ok([task("t1", { client_id: "ruah", client_name: "Ruah", priority: "high", status: "changes" }), task("t2")]));
    const onOpenTask = vi.fn();
    await show(<MyTasks onOpenTask={onOpenTask} />);
    expect(host.textContent).toContain("Sem prazo");
    const row = [...host.querySelectorAll(".myTaskRow")].find((b) => b.textContent?.includes("Tarefa t1")) as HTMLButtonElement;
    expect(row.textContent).toContain("Ruah");
    expect(row.textContent).toContain("Design");
    expect(row.textContent).toContain("Ajustes");
    expect(row.textContent).toContain("Alta");
    await act(async () => { row.click(); });
    expect(onOpenTask).toHaveBeenCalledWith("ruah", "t1");
  });

  it("erro de leitura não vira lista vazia", async () => {
    api.listMyTasks.mockRejectedValue(new Error("Não foi possível carregar suas tarefas agora. Tente de novo."));
    await show(<MyTasks onOpenTask={vi.fn()} />);
    expect(host.querySelector("[role=alert]")?.textContent).toContain("Não foi possível carregar");
    expect(host.textContent).not.toContain("não tem tarefas");
    api.listMyTasks.mockResolvedValue(ok([]));
    const retry = [...host.querySelectorAll("button")].find((b) => b.textContent === "Tentar de novo") as HTMLButtonElement;
    await act(async () => { retry.click(); }); await act(async () => {});
    expect(host.textContent).toContain("Você não tem tarefas abertas");
  });

  it("concluídas só pelo filtro; filtros vão ao servidor", async () => {
    api.listMyTasks.mockResolvedValue(ok([]));
    await show(<MyTasks onOpenTask={vi.fn()} />);
    expect(api.listMyTasks).toHaveBeenLastCalledWith({ clientId: undefined, status: "open", q: "" });
    const selects = host.querySelectorAll("select");
    const set = async (el: HTMLSelectElement, value: string) => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(el, value);
      await act(async () => { el.dispatchEvent(new Event("change", { bubbles: true })); }); await act(async () => {});
    };
    await set(selects[0] as HTMLSelectElement, "ruah");
    await set(selects[1] as HTMLSelectElement, "completed");
    expect(api.listMyTasks).toHaveBeenLastCalledWith({ clientId: "ruah", status: "completed", q: "" });
    expect(host.textContent).toContain("Nenhuma tarefa com esses filtros");
  });

  it("botão do Início mostra quantas estão abertas", async () => {
    api.listMyTasks.mockResolvedValue(ok([task("t1"), task("t2"), task("t3")]));
    const onOpen = vi.fn();
    await show(<MyTasksButton onOpen={onOpen} />);
    const link = host.querySelector("a.myTasksButton") as HTMLAnchorElement;
    expect(link.textContent).toContain("Minhas Tarefas— 3 abertas");
    expect(link.getAttribute("href")).toBe("/minhas-tarefas");
    await act(async () => { link.dispatchEvent(new MouseEvent("click", { bubbles: true, button: 0 })); });
    expect(onOpen).toHaveBeenCalled();
  });
});
