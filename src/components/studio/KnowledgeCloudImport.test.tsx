// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({
  listCloudImport: vi.fn(async () => ({ source: "drive", truncated: false, files: [
    { id: "F1", name: "ROOVE_MANUAL_ID.pdf", mime: "application/pdf", size: 2000, path: "", supported: true, reason: null },
    { id: "F2", name: "Política de Trocas", mime: "application/vnd.google-apps.document", size: null, path: "CONTEUDOS/", supported: true, reason: null },
    { id: "F3", name: "ROOVE 1.mp4", mime: "video/mp4", size: null, path: "", supported: false, reason: "Imagem, vídeo ou áudio" },
  ] })),
  fetchCloudImport: vi.fn(async (_s: string, f: { name: string }) => ({ file_name: f.name.endsWith(".pdf") ? f.name : `${f.name}.docx`, mime: "application/pdf", content_base64: btoa("abc"), needs_ocr: false })),
  teachAndKeepOriginal: vi.fn(async (file: File) => ({ ok: true, document: { id: file.name, name: file.name, summary: "ok" }, knowledge: "", sources: 1, original: "guardado" })),
}));
vi.mock("../../app/studio", async (orig) => ({ ...(await orig<typeof import("../../app/studio")>()), listCloudImport: m.listCloudImport, fetchCloudImport: m.fetchCloudImport }));
vi.mock("../../app/brandKnowledgeUpload", async (orig) => ({ ...(await orig<typeof import("../../app/brandKnowledgeUpload")>()), teachAndKeepOriginal: m.teachAndKeepOriginal }));
import KnowledgeCloudImport from "./KnowledgeCloudImport";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });

describe("Importar do Drive ou do Canva", () => {
  it("lista a pasta, pula o que já foi lido e o que não tem texto, e ensina o resto", async () => {
    const onLearned = vi.fn();
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<KnowledgeCloudImport kind="institucional" knownNames={["ROOVE_MANUAL_ID.pdf"]} onLearned={onLearned} onClose={() => undefined} />); });
    const input = host.querySelector('input[type="url"]') as HTMLInputElement;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => { set.call(input, "https://drive.google.com/drive/folders/1q7psA_PM9Xt"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { (host.querySelector("form") as HTMLFormElement).requestSubmit(); });
    await act(async () => {});
    const boxes = [...host.querySelectorAll<HTMLInputElement>('.kbCloudList input[type="checkbox"]')];
    expect(boxes.map((b) => [b.checked, b.disabled])).toEqual([[false, false], [true, false], [false, true]]);
    expect(host.textContent).toContain("já está no Conhecimento");
    const go = [...host.querySelectorAll("button")].find((b) => b.textContent?.startsWith("Importar 1")) as HTMLButtonElement;
    await act(async () => { go.click(); });
    await act(async () => {});
    expect(m.fetchCloudImport).toHaveBeenCalledTimes(1);
    expect((m.teachAndKeepOriginal.mock.calls[0][0] as File).name).toBe("Política de Trocas.docx");
    expect(onLearned).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain("Aprendido");
  });
});
