// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("../../app/taskWork", () => ({ listProduced: m.list }));
import TaskProduced from "./TaskProduced";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); window.history.replaceState({}, "", "/"); });

describe("Ir para o job", () => {
  it("lista o que foi produzido e abre cada item no lugar dele", async () => {
    m.list.mockResolvedValue({ task_id: "t1", items: [
      { module: "email_marketing", module_label: "E-mail Marketing", record_id: "e1", deliverable: "E-mail Black", created_at: null,
        name: "Black começa", removed: false, status: "Rascunho", route: "email_marketing", query: "campanha=e1" },
      { module: "redacao", module_label: "Redação", record_id: "d2", deliverable: "", created_at: null,
        name: "Removido", removed: true, status: "", route: null, query: null },
    ] });
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => createRoot(host).render(<TaskProduced taskId="t1" />));
    await act(async () => {});
    expect(host.textContent).toContain("Produzido a partir desta tarefa");
    const [email, removed] = [...host.querySelectorAll("button")];
    expect(removed.disabled).toBe(true);
    await act(async () => email.click());
    expect(window.location.pathname + window.location.search).toBe("/email-marketing?campanha=e1");
  });

  it("sem nada produzido, não aparece", async () => {
    m.list.mockResolvedValue({ task_id: "t1", items: [] });
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => createRoot(host).render(<TaskProduced taskId="t1" />));
    await act(async () => {});
    expect(host.innerHTML).toBe("");
  });
});
