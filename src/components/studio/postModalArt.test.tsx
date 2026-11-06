// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const upload = vi.hoisted(() => ({ uploadArt: vi.fn(), importArt: vi.fn() }));
vi.mock("../../app/artUpload", async (original) => ({ ...(await original<typeof import("../../app/artUpload")>()), ...upload }));

import PostModal from "./PostModal";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const draft = { date: "2026-11-05", time: "19:00", format: "reels" as const, pillar: "", title: "", hook: "", caption_draft: "", rationale: "" };
const noop = async () => undefined;

describe("PostModal: arte na criação", () => {
  it("nova pauta já tem a área da arte e o envio não precisa da pauta salva", async () => {
    upload.uploadArt.mockResolvedValue("https://x.supabase.co/storage/v1/object/public/ig-media/studio-art/m2/nova/a.mp4");
    const onSave = vi.fn(async () => true);
    await act(async () => { root.render(<PostModal item={null} initial={draft} handle="@m2" pillars={[]} canManage busy={false} error={null}
      onClose={() => undefined} onSave={onSave} onStatus={noop} onDelete={noop} />); });
    expect(host.textContent).toContain("Arraste a arte aqui");
    const input = host.querySelector<HTMLInputElement>('.postArtDrop input[type="file"]')!;
    const file = new File(["x"], "reels.mp4", { type: "video/mp4" });
    Object.defineProperty(input, "files", { value: [file] });
    await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
    await act(async () => {});
    expect(upload.uploadArt).toHaveBeenCalledWith(null, file);
    expect(host.textContent).toContain("1 arquivo");
    expect(host.textContent).toContain("Criar pauta");
  });

  it("traz a arte de um link do Canva e troca link do Drive pelo arquivo na mesma posição", async () => {
    const STORED = "https://x.supabase.co/storage/v1/object/public/ig-media/studio-art/latinas/nova/c.jpg";
    upload.importArt.mockResolvedValue({ public_url: STORED, content_type: "image/jpeg", note: "Prévia do Canva (resolução de visualização)." });
    const DRIVE = "https://drive.google.com/file/d/1AbCdEfGhIjKlMn/view";
    await act(async () => { root.render(<PostModal item={null} initial={{ ...draft, art_url: DRIVE }} handle="@latinas" pillars={[]} canManage busy={false} error={null}
      onClose={() => undefined} onSave={async () => true} onStatus={noop} onDelete={noop} />); });
    const input = host.querySelector<HTMLInputElement>('input[aria-label="Link da arte no Drive ou Canva"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "https://canva.link/sym7z8mpql3cf9l");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === "Trazer arte")!.click(); });
    expect(upload.importArt).toHaveBeenCalledWith(null, "https://canva.link/sym7z8mpql3cf9l");
    expect(host.textContent).toContain("2 arquivos");
    expect(host.textContent).toContain("Prévia do Canva");
    await act(async () => { host.querySelector<HTMLButtonElement>('[aria-label="Trazer arquivo da arte 1"]')!.click(); });
    expect(upload.importArt).toHaveBeenLastCalledWith(null, DRIVE);
    expect(host.querySelector('[aria-label="Trazer arquivo da arte 1"]')).toBeNull();
  });
});
