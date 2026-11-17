// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ImportField, ImportPreview } from "../../app/brandImport";

const api = vi.hoisted(() => ({ previewBrandImport: vi.fn(), applyBrandImport: vi.fn() }));
const studio = vi.hoisted(() => ({ getKnowledge: vi.fn(), teachFromFile: vi.fn() }));
vi.mock("../../app/brandImport", () => api);
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));
const upload = vi.hoisted(() => ({ teachAndKeepOriginal: vi.fn() }));
vi.mock("../../app/brandKnowledgeUpload", async (original) => ({ ...(await original<typeof import("../../app/brandKnowledgeUpload")>()), ...upload }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "aurora", getActiveClientName: () => "Aurora" }));
vi.mock("../../hooks/dashboard/cache", () => ({ clearDashboardCacheByPrefix: vi.fn() }));

import BrandImport from "./BrandImport";
import { BRAND_PROFILE_SAVED } from "../../app/studio";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;

const field = (over: Partial<ImportField>): ImportField => ({ key: "x", label: "X", group: "identidade", kind: "text", targets: [], operational: false,
  status: "found", value: null, current: null, changed: true, source: null, notes: [], max_length: 1000, ...over });

const PREVIEW: ImportPreview = {
  ok: true, document: { id: "doc-1", name: "planejamento-aurora.pdf", chars_total: 900, read_chars: 900, parts: 1, partial: false },
  counts: { found: 3, ambiguous: 1, missing: 1 }, missing: ["Diferenciais"],
  fields: [
    field({ key: "tone_of_voice", label: "Tom de voz", value: "Acolhedor e didático.", current: "Tom antigo",
      source: { excerpt: "Tom de voz: acolhedor, curioso e didático", verified: true, location: "Trecho 2 de 4" } }),
    field({ key: "positioning", label: "Posicionamento", status: "ambiguous", value: "A mais premium.", current: "Atual",
      source: { excerpt: "a mais premium do Brasil", verified: false, location: null }, notes: ["Não localizei o trecho citado no documento. Confira antes de aplicar."] }),
    field({ key: "pillars", label: "Pilares editoriais e pesos", group: "operacao", kind: "pillars", operational: true,
      value: [{ name: "Origem", weight: 50, description: "" }, { name: "Preparo", weight: 30, description: "" }], current: null,
      notes: ["Os pesos somam 80%. Ajuste para 100% antes de aplicar."] }),
    field({ key: "posts_per_week_by_platform", label: "Posts por semana por canal", group: "operacao", kind: "frequency", operational: true,
      value: { instagram: 4, tiktok: 2 }, current: { instagram: 3 } }),
    field({ key: "editorial_platforms", label: "Plataformas", group: "operacao", kind: "channels", operational: true,
      value: ["instagram", "tiktok"], current: ["instagram"] }),
    field({ key: "competitors", label: "Concorrentes", group: "negocio", kind: "competitors",
      value: [{ name: "Café Serra Alta", instagram_handle: null, website: null }], current: null }),
    field({ key: "differentiators", label: "Diferenciais", group: "negocio", status: "missing" }),
  ],
};

beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  studio.getKnowledge.mockResolvedValue({ knowledge: "", sources: 1, updated_at: null,
    documents: [{ id: "doc-1", name: "planejamento-aurora.pdf", kind: "institucional", summary: null, facts_added: 0, truncated: false, created_at: "2026-11-17T10:00:00Z" },
      { id: "c1", name: "Conversa com a IA", kind: "conversa", summary: null, facts_added: 1, truncated: false, created_at: "2026-11-17T10:00:00Z" }] });
  api.previewBrandImport.mockResolvedValue(PREVIEW);
  api.applyBrandImport.mockResolvedValue({ ok: true, applied: ["Tom de voz"], profile: { tone_of_voice: "Acolhedor e didático." } });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(text));
const click = async (el: Element | null | undefined) => { await act(async () => { (el as HTMLElement).click(); }); };
const check = (key: string) => host.querySelector<HTMLInputElement>(`[data-field="${key}"] .bcFieldHead input`)!;
const fieldEl = (key: string) => host.querySelector<HTMLElement>(`[data-field="${key}"]`)!;

async function readPreview() {
  await show(<BrandImport />);
  await click(button("Ler e montar prévia"));
}

describe("Importar configurações do planejamento", () => {
  it("lista só documentos, lê uma vez e mostra a prévia com origem, sem nada marcado", async () => {
    await readPreview();
    expect([...host.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["planejamento-aurora.pdf"]);
    expect(api.previewBrandImport).toHaveBeenCalledTimes(1);
    expect(api.previewBrandImport).toHaveBeenCalledWith("doc-1");
    expect(host.textContent).toContain("3 encontrado(s), 1 para revisar, 1 não encontrado(s)");
    expect(host.textContent).toContain("Não encontrados no documento");
    expect(fieldEl("tone_of_voice").textContent).toContain("Trecho 2 de 4");
    expect(fieldEl("tone_of_voice").textContent).toContain("Atual: Tom antigo");
    expect(fieldEl("positioning").textContent).toContain("origem não confirmada");
    expect(fieldEl("differentiators")).toBeNull();
    expect(host.querySelectorAll('.bcFieldHead input:checked')).toHaveLength(0);
    expect(button("Revisar e aplicar")?.disabled).toBe(true);
    expect(api.applyBrandImport).not.toHaveBeenCalled();
  });

  it("selecionar os encontrados não marca ambíguos nem regras operacionais", async () => {
    await readPreview();
    await click(button("Selecionar os encontrados"));
    expect(check("tone_of_voice").checked).toBe(true);
    expect(check("positioning").checked).toBe(false);
    expect(check("pillars").checked).toBe(false);
    expect(check("posts_per_week_by_platform").checked).toBe(false);
    expect(check("competitors").checked).toBe(false);  // cadastra no Benchmarking: só marcando
  });

  it("concorrentes aprovados mostram o que entrou no Benchmarking e no Clipping", async () => {
    api.applyBrandImport.mockResolvedValue({ ok: true, applied: ["Concorrentes"], competitors: { criados: ["Café Serra Alta"], ja_cadastrados: [],
      fora_do_plano: [], no_clipping: ["Café Serra Alta"], fora_do_clipping: [] } });
    await readPreview();
    await click(check("competitors"));
    const handle = host.querySelector<HTMLInputElement>('[aria-label="Instagram do concorrente 1"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(handle, "@serraalta");
      handle.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(button("Revisar e aplicar"));
    await click(button("Confirmar e aplicar"));
    expect(api.applyBrandImport.mock.calls[0][1].competitors.value).toEqual([{ name: "Café Serra Alta", instagram_handle: "serraalta", website: null }]);
    expect(host.textContent).toContain("cadastrados no Benchmarking: Café Serra Alta");
    expect(host.textContent).toContain("monitorados no Clipping: Café Serra Alta");
    expect(host.textContent).toContain("A IA já usa o que foi aplicado");
  });

  it("versão nova do planejamento: esconde o que já está igual, com opção de ver tudo", async () => {
    api.previewBrandImport.mockResolvedValue({ ...PREVIEW, fields: PREVIEW.fields.map((f) => (f.key === "positioning" ? { ...f, changed: false } : f)) });
    await readPreview();
    expect(fieldEl("positioning")).toBeNull();
    expect(host.textContent).toContain("1 campo(s) igual(is) escondido(s)");
    await click(host.querySelector<HTMLInputElement>(".bcOnlyChanged input"));
    expect(fieldEl("positioning")).not.toBeNull();
  });

  it("documento longo informa que foi lido inteiro, em partes", async () => {
    api.previewBrandImport.mockResolvedValue({ ...PREVIEW, document: { ...PREVIEW.document, parts: 3, read_chars: 140000 } });
    await readPreview();
    expect(host.textContent).toContain("lido inteiro, em 3 partes");
  });

  it("pesos que não fecham 100% bloqueiam a aplicação até a correção", async () => {
    await readPreview();
    await click(check("pillars"));
    expect(fieldEl("pillars").textContent).toContain("Os pesos somam 80%. Ajuste para 100%.");
    expect(button("Revisar e aplicar")?.disabled).toBe(true);
    const weight = host.querySelector<HTMLInputElement>('[aria-label="Peso do pilar 2"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(weight, "50");
      weight.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(fieldEl("pillars").textContent).toContain("Soma dos pesos: 100%");
    expect(button("Revisar e aplicar")?.disabled).toBe(false);
  });

  it("frequência de canal fora das Plataformas pede para marcar as Plataformas", async () => {
    await readPreview();
    await click(check("posts_per_week_by_platform"));
    expect(fieldEl("posts_per_week_by_platform").textContent).toContain("Inclua TikTok nas Plataformas");
    expect(button("Revisar e aplicar")?.disabled).toBe(true);
    await click(check("editorial_platforms"));
    expect(button("Revisar e aplicar")?.disabled).toBe(false);
  });

  it("só aplica depois da confirmação e envia apenas os campos marcados", async () => {
    const saved = vi.fn();
    window.addEventListener(BRAND_PROFILE_SAVED, saved);
    const onApplied = vi.fn();
    await show(<BrandImport onApplied={onApplied} />);
    await click(button("Ler e montar prévia"));
    await click(check("tone_of_voice"));
    await click(button("Revisar e aplicar (1)"));
    expect(api.applyBrandImport).not.toHaveBeenCalled();
    expect(host.textContent).toContain("Aplicar 1 configuração(ões)?");
    expect(host.querySelector(".bcConfirm")?.textContent).toContain("Tom de voz: Acolhedor e didático.");
    await click(button("Confirmar e aplicar"));
    expect(api.applyBrandImport).toHaveBeenCalledWith("doc-1", { tone_of_voice: { value: "Acolhedor e didático.", mode: "replace" } });
    expect(host.textContent).toContain("Aplicado: Tom de voz");
    expect(saved).toHaveBeenCalled();
    expect(onApplied).toHaveBeenCalled();
    window.removeEventListener(BRAND_PROFILE_SAVED, saved);
  });

  it("acrescentar ao atual vai como modo append", async () => {
    await readPreview();
    await click(check("tone_of_voice"));
    await click(fieldEl("tone_of_voice").querySelectorAll<HTMLInputElement>('input[type=radio]')[1]);
    await click(button("Revisar e aplicar"));
    await click(button("Confirmar e aplicar"));
    expect(api.applyBrandImport.mock.calls[0][1].tone_of_voice.mode).toBe("append");
  });

  it("erro do servidor (ex.: PDF sem texto) aparece com a orientação", async () => {
    api.previewBrandImport.mockRejectedValue(new Error("Este documento tem pouco texto legível para importar configurações. Se for um PDF escaneado…"));
    await readPreview();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("PDF escaneado");
  });

  it("sem documentos, orienta a enviar o planejamento", async () => {
    studio.getKnowledge.mockResolvedValue({ knowledge: "", sources: 0, updated_at: null, documents: [] });
    await show(<BrandImport />);
    expect(host.textContent).toContain("Nenhum documento enviado ainda");
    expect(button("Ler e montar prévia")?.disabled).toBe(true);
  });
});
