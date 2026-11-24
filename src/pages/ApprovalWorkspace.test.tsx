// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ApprovalWorkspace from "./ApprovalWorkspace";

const studio = vi.hoisted(() => ({
  getPipeline: vi.fn(), decideCalendarItem: vi.fn(), updateCalendarItem: vi.fn(), sendForApproval: vi.fn(), getItemHistory: vi.fn(),
  deleteApprovalContent: vi.fn(),
}));
vi.mock("../app/studio", async (original) => ({ ...(await original<typeof import("../app/studio")>()), ...studio }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "tenant-a", getActiveClientName: () => "Marca A" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title, controls }: { title: string; controls?: React.ReactNode }) => <header><h1>{title}</h1>{controls}</header> }));
vi.mock("../components/studio/ArtCarousel", () => ({ default: ({ images }: { images: string[] }) => <img src={images[0]} alt="Arte" /> }));
vi.mock("../components/studio/PostComments", () => ({ default: ({ itemId }: { itemId: string }) => <div data-testid="comments">Comentários {itemId}</div> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const item = (id: string, stage: "revisao_interna" | "com_cliente", title: string) => ({
  id, client_id: "tenant-a", month: "2026-11", scheduled_at: "2026-11-20T12:00:00Z", format: "imagem" as const,
  channel: "instagram" as const, pillar: "Marca", title, hook: "Gancho", caption_draft: "Legenda", rationale: null, signals: {},
  status: "em_revisao" as const, review_note: null, origin: "manual" as const, art_url: "https://cdn.test/arte.jpg", reviewed_by: null,
  reviewed_at: null, stage, request: null, client_feedback: null,
});

describe("ApprovalWorkspace", () => {
  let host: HTMLDivElement; let root: ReturnType<typeof createRoot>;
  beforeEach(() => {
    host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
    studio.getPipeline.mockResolvedValue({ items: [item("i1", "revisao_interna", "Interna"), item("f1", "com_cliente", "Final")] });
    studio.getItemHistory.mockResolvedValue({ events: [] }); studio.updateCalendarItem.mockResolvedValue({ item: {} });
    studio.decideCalendarItem.mockResolvedValue({ item: {} }); studio.sendForApproval.mockResolvedValue({ link: "https://example.test/aprovar/token" });
    studio.deleteApprovalContent.mockResolvedValue({ ok: true });
  });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.clearAllMocks(); vi.restoreAllMocks(); });

  async function render(mode: "internal" | "final", isAgency = mode === "internal", canDeleteContent = false) {
    await act(async () => root.render(<ApprovalWorkspace mode={mode} isAgency={isAgency} canDeleteContent={canDeleteContent} onOpenCalendar={vi.fn()} />));
    await act(async () => { await Promise.resolve(); });
  }

  it("mostra somente pendências da etapa e não oferece Abrir Editável", async () => {
    await render("internal");
    expect(host.textContent).toContain("Aprovação Interna"); expect(host.textContent).toContain("Interna");
    expect(host.textContent).not.toContain("Final"); expect(host.textContent).not.toContain("Abrir Editável");
    expect(host.textContent).toContain("Solicitar ajuste"); expect(host.textContent).toContain("Aprovar agora");
  });

  it("aprova internamente pelo fluxo existente e atualiza a fila", async () => {
    studio.getPipeline.mockResolvedValueOnce({ items: [item("i1", "revisao_interna", "Interna")] }).mockResolvedValueOnce({ items: [] });
    await render("internal");
    const button = [...host.querySelectorAll("button")].find((node) => node.textContent?.includes("Aprovar agora"))!;
    await act(async () => { button.click(); await Promise.resolve(); });
    expect(studio.sendForApproval).toHaveBeenCalledWith({ month: "2026-11", item_ids: ["i1"] });
    expect(host.textContent).toContain("Peça aprovada internamente"); expect(host.querySelector(".approvalQueue strong")?.textContent).not.toBe("Interna");
  });

  it("aprova na etapa final e solicita ajuste com comentário obrigatório", async () => {
    await render("final", false);
    const textarea = host.querySelector<HTMLTextAreaElement>(".approvalNotes>label textarea")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(textarea, "Trocar a imagem");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const adjust = [...host.querySelectorAll("button")].find((node) => node.textContent?.includes("Solicitar ajuste"))!;
    await act(async () => { adjust.click(); await Promise.resolve(); });
    expect(studio.decideCalendarItem).toHaveBeenCalledWith("f1", "rejeitado", "Trocar a imagem");
  });

  it("alterna visualização e abre o Calendário existente", async () => {
    const open = vi.fn();
    await act(async () => root.render(<ApprovalWorkspace mode="final" isAgency={false} canDeleteContent={false} onOpenCalendar={open} />));
    await act(async () => { await Promise.resolve(); });
    const mobile = [...host.querySelectorAll("button")].find((node) => node.textContent?.includes("Mobile"))!;
    await act(async () => mobile.click());
    expect(mobile.getAttribute("aria-pressed")).toBe("true");
    const calendar = [...host.querySelectorAll("button")].find((node) => node.textContent?.includes("Calendário"))!;
    await act(async () => calendar.click()); expect(open).toHaveBeenCalledTimes(1);
  });

  it.each(["internal", "final"] as const)("exclui conteúdo da fila %s somente com permissão específica", async (mode) => {
    const target = mode === "internal" ? "i1" : "f1";
    const title = mode === "internal" ? "Interna" : "Final";
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await render(mode, true, true);
    const remove = [...host.querySelectorAll("button")].find((node) => node.textContent === "Excluir conteúdo")!;
    await act(async () => { remove.click(); await Promise.resolve(); });
    expect(confirm).toHaveBeenCalledWith(`Excluir o conteúdo “${title}” da fila de aprovação? O histórico será preservado.`);
    expect(studio.deleteApprovalContent).toHaveBeenCalledWith(target);
    expect(host.textContent).toContain("O histórico da peça foi preservado");
    expect([...host.querySelectorAll(".approvalQueue strong")].some((node) => node.textContent === title)).toBe(false);
    expect(host.textContent).not.toContain("Aprovar agora");
  });

  it("não oferece exclusão a quem apenas aprova", async () => {
    await render("internal", true, false);
    expect(host.textContent).toContain("Aprovar agora");
    expect(host.textContent).not.toContain("Excluir conteúdo");
    expect(studio.deleteApprovalContent).not.toHaveBeenCalled();
  });
});
