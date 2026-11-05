// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const upload = vi.hoisted(() => ({ uploadArt: vi.fn() }));
vi.mock("../../app/artUpload", () => upload);

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
});
