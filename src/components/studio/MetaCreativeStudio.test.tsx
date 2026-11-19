// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetaCreativeStudio from "./MetaCreativeStudio";
import type { CalendarItem } from "../../app/studio";
import type { AdPayload } from "../../app/metaAds";
import { listLibrary, uploadLibraryFile } from "../../app/library";

vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
vi.mock("../../app/library", () => ({
  listLibrary: vi.fn(),
  uploadLibraryFile: vi.fn(),
  previewKind: (item: {mime_type?: string}) => item.mime_type?.startsWith("image/") ? "image" : "file",
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const ad = (): AdPayload["ad"] => ({
  primary_text: "Black Friday Roove", headline: "Acesso antecipado",
  description: "Cupons especiais", cta: "SIGN_UP",
  link: "https://roove.com.br/black", image_url: "", calendar_item_id: null,
});
const calendar = [{ id: "post-1", title: "Arte calendário", art_url: "https://cdn.example.org/calendar.jpg" }] as CalendarItem[];
let host: HTMLDivElement;
beforeEach(() => {
  vi.mocked(listLibrary).mockResolvedValue({ items: [
    {id:"asset-1",title:"Arte da Roove",url:"https://cdn.example.org/roove.jpg",kind:"arquivo",
      category:"foto",side:"mugo",mime_type:"image/jpeg"},
  ], approved: [], categories: {} as never, team: true });
});
afterEach(() => {host?.remove(); vi.clearAllMocks();});

describe("Mídia On — Estúdio de criativos", () => {
  it("oferece biblioteca da empresa, seleção real e as três prévias de proporções", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), choose = vi.fn();
    await act(async () => {
      root.render(<MetaCreativeStudio clientId="roove" month="2026-11" calendar={calendar} ad={ad()} onChoose={choose} />);
    });
    await act(async () => {});
    expect(listLibrary).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain("Arte da Roove");
    expect(host.textContent).toContain("Arte calendário");
    const gallery = [...host.querySelectorAll("button")].find((b) => b.title === "Arte da Roove");
    await act(async () => gallery?.click());
    expect(choose).toHaveBeenCalledWith({image_url:"https://cdn.example.org/roove.jpg",calendar_item_id:null, media_type:"image", video_url:"",instagram_post_id:null});
    const story = [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Stories / Reels"));
    await act(async () => story?.click());
    expect(story?.getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector(".metaCreativeDevice")?.className).toContain("is-story");
    act(() => root.unmount());
  });
  it("salva novas imagens pela Biblioteca antes de selecionar o criativo", async () => {
    vi.mocked(uploadLibraryFile).mockResolvedValue({
      item: {id:"new",title:"Nova arte",url:"https://cdn.example.org/new.png",kind:"arquivo",
        category:"foto",side:"mugo",mime_type:"image/png"},
    });
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), choose = vi.fn();
    await act(async () => root.render(<MetaCreativeStudio clientId="roove" month="2026-11"
      calendar={[]} ad={ad()} onChoose={choose} />));
    await act(async () => {});
    const input = host.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["test"], "criativo.png", {type:"image/png"});
    Object.defineProperty(input, "files", { configurable:true, value:[file] });
    await act(async () => input.dispatchEvent(new Event("change",{bubbles:true})));
    expect(uploadLibraryFile).toHaveBeenCalled();
    expect(choose).toHaveBeenCalledWith({image_url:"https://cdn.example.org/new.png",calendar_item_id:null, media_type:"image", video_url:"",instagram_post_id:null});
    act(() => root.unmount());
  });
});
