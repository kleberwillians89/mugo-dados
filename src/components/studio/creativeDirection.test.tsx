// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const briefs = vi.hoisted(() => ({ listBriefs: vi.fn(async () => ({ team: true, briefs: [{ id: "0b6f2c1e-6a43-4b7e-9d1a-3f0f0c9d2a11", brief: { title: "Black Friday decant" } }] })) }));
vi.mock("../../app/briefs", async (original) => ({ ...(await original<typeof import("../../app/briefs")>()), ...briefs }));
const studio = vi.hoisted(() => ({ suggestCreativeDirection: vi.fn(), generateBriefing: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));
vi.mock("./PostReferences", () => ({ default: () => null }));
vi.mock("./PostComments", () => ({ default: () => null }));
vi.mock("./ItemHistory", () => ({ default: () => null }));
vi.mock("./AiSuggestionCard", () => ({ default: () => null }));

import PostModal from "./PostModal";
import { draftFrom } from "../../app/studioCalendar";
import type { CalendarItem } from "../../app/studio";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const ITEM = { id: "i1", client_id: "ruah", month: "2026-11-01", scheduled_at: "2026-11-20T22:00:00+00:00", format: "carrossel", channel: "instagram",
  pillar: null, title: "3 perfumes", hook: null, caption_draft: "Legenda", rationale: null, signals: {}, status: "rascunho", review_note: null,
  origin: "manual", reviewed_by: null, reviewed_at: null, creative_direction: { concept: "Minha ideia" } } as unknown as CalendarItem;
const noop = async () => undefined;
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;
const type = async (el: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); });
};
const field = (label: string) => [...host.querySelectorAll(".postDirection label")].find((l) => l.textContent?.startsWith(label))!
  .querySelector("input,textarea") as HTMLInputElement | HTMLTextAreaElement;
async function open(item: CalendarItem = ITEM, onSave = vi.fn(async () => true), clientMode = false) {
  await act(async () => { root.render(<PostModal item={item} initial={draftFrom(item)} handle="@ruah" pillars={[]} canManage busy={false} error={null}
    onClose={() => undefined} onSave={onSave} onStatus={noop} onDelete={noop} clientMode={clientMode} onSendForApproval={() => undefined} />); });
  await act(async () => {});
  if (!clientMode) await act(async () => { btn("Editar peça")?.click(); });  // a edição da peça abre pelo botão no Briefing
  return onSave;
}

describe("Calendário: Direcionamento Criativo", () => {
  it("o Briefing da peça é o primeiro bloco, com 'Editar peça' abrindo a edição logo abaixo", async () => {
    await act(async () => { root.render(<PostModal item={ITEM} initial={draftFrom(ITEM)} handle="@ruah" pillars={[]} canManage busy={false} error={null}
      onClose={() => undefined} onSave={vi.fn(async () => true)} onStatus={noop} onDelete={noop} onSendForApproval={() => undefined} />); });
    const panel = host.querySelector(".postPanel")!;
    const blocks = () => [...panel.children].filter((el) => !el.classList.contains("postPanelHead"));
    expect(blocks()[0].querySelector("summary")?.textContent).toBe("Briefing da peça");
    expect(blocks()[0].textContent).toContain("Minha ideia");            // o direcionamento salvo aparece no briefing
    expect(host.querySelector(".postDirection")).toBeNull();               // edição fechada até clicar
    await act(async () => { btn("Editar peça")!.click(); });
    expect(blocks()[1].getAttribute("aria-label")).toBe("Direcionamento Criativo");
    expect(btn("Fechar edição")).toBeTruthy();
    expect(host.textContent).not.toContain("Gerar briefing com IA");
    expect(host.textContent).not.toContain("Refazer com IA");
    // O resto da janela continua: legenda, envio ao cliente, aprovar.
    expect(host.textContent).toContain("Legenda");
    expect(btn("Enviar para o cliente aprovar")).toBeTruthy();
    expect(btn("Aprovar")).toBeTruthy();
  });

  it("texto livre é editado e salvo junto com a pauta, com o briefing de referência", async () => {
    const onSave = await open();
    await type(field("Título / conceito"), "Verão sem peso");
    await type(field("Textos necessários"), "Capa: 3 perfumes leves");
    const select = host.querySelector(".postDirection select") as HTMLSelectElement;
    await act(async () => { select.value = "0b6f2c1e-6a43-4b7e-9d1a-3f0f0c9d2a11"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(host.textContent).toContain("O direcionamento mudou");
    await act(async () => { btn("Salvar alterações")!.click(); });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0].creative_direction).toEqual({ concept: "Verão sem peso", texts: "Capa: 3 perfumes leves",
      brief_id: "0b6f2c1e-6a43-4b7e-9d1a-3f0f0c9d2a11" });
  });

  it("a IA é opcional e nunca troca o texto da pessoa sem ela escolher", async () => {
    studio.suggestCreativeDirection.mockResolvedValue({ suggestion: { concept: "Sugestão da IA", instructions: "Luz natural" }, based_on: {} });
    await open();
    await act(async () => { btn("Sugerir com IA")!.click(); });
    expect(studio.suggestCreativeDirection).toHaveBeenCalledWith("i1", { concept: "Minha ideia" }, "");
    expect(host.textContent).toContain("Sugestão da IA");
    expect(field("Título / conceito").value).toBe("Minha ideia");         // nada mudou sozinho
    await act(async () => { btn("Preencher só os campos vazios")!.click(); });
    expect(field("Título / conceito").value).toBe("Minha ideia");         // campo escrito pela pessoa fica
    expect(field("Instruções para a peça").value).toBe("Luz natural");    // campo vazio recebeu a sugestão
  });

  it("substituir ou acrescentar só acontece no clique", async () => {
    studio.suggestCreativeDirection.mockResolvedValue({ suggestion: { concept: "Outra ideia" }, based_on: {} });
    await open({ ...ITEM, creative_direction: { concept: "Minha ideia", texts: "Capa" } } as CalendarItem);
    await act(async () => { btn("Sugerir com IA")!.click(); });
    await act(async () => { btn("Acrescentar ao meu texto")!.click(); });
    expect(field("Título / conceito").value).toBe("Minha ideia Outra ideia");
    studio.suggestCreativeDirection.mockResolvedValue({ suggestion: { texts: "Capa nova" }, based_on: {} });
    await act(async () => { btn("Sugerir com IA")!.click(); });
    await act(async () => { btn("Substituir o meu texto")!.click(); });
    expect(field("Textos necessários").value).toBe("Capa nova");
  });

  it("o direcionamento salvo permite enviar para quem cria e o cliente não vê o bloco", async () => {
    await open();
    expect(btn("Enviar para…")).toBeTruthy();
    await open({ ...ITEM, status: "em_revisao" } as CalendarItem, vi.fn(async () => true), true);
    expect(host.querySelector(".postDirection")).toBeNull();
  });
});
