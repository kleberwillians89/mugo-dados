// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({
  listLibraryCloud: vi.fn(async () => ({ source: "drive", truncated: false, files: [
    { id: "F1", name: "ROOVE_LOGO.png", mime: "image/png", size: 2000, path: "", supported: true, reason: null, category: "logo" },
    { id: "F2", name: "ROOVE 1.mp4", mime: "video/mp4", size: 90_000_000, path: "Vídeos/", supported: true, reason: null, category: "video" },
    { id: "F3", name: "arte.ai", mime: "application/postscript", size: null, path: "", supported: false, reason: "Arquivo de design", category: "documento" },
  ] })),
  importLibraryCloud: vi.fn(async (_s: string, f: { id: string; name: string }, category: string) => ({ item: { id: `i-${f.id}`, title: f.name, category } })),
}));
vi.mock("../../app/library", async (orig) => ({ ...(await orig<typeof import("../../app/library")>()), listLibraryCloud: m.listLibraryCloud, importLibraryCloud: m.importLibraryCloud }));
import LibraryCloudImport from "./LibraryCloudImport";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });

describe("Biblioteca · importar do Drive ou do Canva", () => {
  it("sugere a categoria, pula o que já existe e copia o resto", async () => {
    const onAdded = vi.fn();
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<LibraryCloudImport knownTitles={["ROOVE_LOGO.png"]} onAdded={onAdded} onClose={() => undefined} />); });
    const input = host.querySelector('input[type="url"]') as HTMLInputElement;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => { set.call(input, "https://drive.google.com/drive/folders/1q7psA_PM9Xt"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { (host.querySelector("form") as HTMLFormElement).requestSubmit(); });
    await act(async () => {});
    const boxes = [...host.querySelectorAll<HTMLInputElement>('.libCloudList input[type="checkbox"]')];
    expect(boxes.map((b) => [b.checked, b.disabled])).toEqual([[false, false], [true, false], [false, true]]);
    expect([...host.querySelectorAll("select")].map((s) => s.value)).toEqual(["logo", "video"]);
    const go = [...host.querySelectorAll("button")].find((b) => b.textContent?.startsWith("Importar 1")) as HTMLButtonElement;
    await act(async () => { go.click(); });
    await act(async () => {});
    expect(m.importLibraryCloud).toHaveBeenCalledTimes(1);
    expect(m.importLibraryCloud.mock.calls[0][2]).toBe("video");
    expect(onAdded).toHaveBeenCalledWith(expect.objectContaining({ id: "i-F2" }));
    expect(host.textContent).toContain("Na Biblioteca");
  });
});
