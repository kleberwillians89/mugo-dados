// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), fromTask: vi.fn(), toEmail: vi.fn(), save: vi.fn() }));
vi.mock("../../app/contentOps", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listDocuments: m.list, getDocument: m.get, documentToEmail: m.toEmail, saveDocument: m.save,
}));
vi.mock("../../app/taskWork", async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), createDocumentFromTask: m.fromTask }));
// O seletor de tarefas já tem testes próprios: aqui entrega direto a tarefa escolhida.
vi.mock("../work/KanbanTaskStart", () => ({
  default: ({ actions }: { actions: (ctx: unknown, deliverable: string) => React.ReactNode }) =>
    <div>{actions({ task: { id: "t1", title: "Black Ruah" }, context: {}, brief_id: null }, "Legenda do Reels")}</div>,
}));
import Redacao from "./Redacao";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); vi.restoreAllMocks(); });
const DOC = { id: "d1", title: "Black Ruah · Legenda do Reels", kind: "legenda", status: "rascunho", content_html: "<p>Texto pronto.</p>",
  content_text: "Texto pronto.", calendar_item_id: null, updated_at: new Date().toISOString() };
const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.startsWith(label)) as HTMLButtonElement;

async function render() {
  m.list.mockResolvedValue({ documents: [] });
  m.get.mockResolvedValue({ document: DOC });
  host = document.createElement("div"); document.body.appendChild(host);
  await act(async () => createRoot(host).render(<Redacao canManage onOpenEmail={vi.fn()} />));
  await act(async () => {});
}

describe("Redação com o Kanban e o Enviar para…", () => {
  it("cria o documento a partir da tarefa e abre ele", async () => {
    m.fromTask.mockResolvedValue({ created: { id: "d1", title: DOC.title, kind: "legenda" }, existing: [] });
    await render();
    await act(async () => button("Selecionar tarefa do Kanban").click());
    await act(async () => button("Escrever com a IA da marca").click());
    await act(async () => {});
    expect(m.fromTask).toHaveBeenCalledWith("t1", { mode: "ia", deliverable: "Legenda do Reels" });
    expect(m.get).toHaveBeenCalledWith("d1");
    expect(host.textContent).toContain("Documento criado a partir da tarefa");
  });

  it("manda o texto para o E-mail Marketing depois de confirmar", async () => {
    m.fromTask.mockResolvedValue({ created: null, existing: [{ id: "d1", title: DOC.title }] });
    m.toEmail.mockResolvedValue({ campaign: { id: "e1", name: DOC.title, status: "rascunho" } });
    await render();
    await act(async () => button("Selecionar tarefa do Kanban").click());
    await act(async () => button("Começar em branco").click());
    await act(async () => {});
    expect(host.textContent).toContain("já tem um documento");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await act(async () => button("E-mail Marketing").click());
    expect(m.toEmail).toHaveBeenCalledWith("d1");
    expect(host.textContent).toContain("criado no E-mail Marketing");
    expect(button("Abrir o E-mail Marketing")).toBeTruthy();
  });
});
