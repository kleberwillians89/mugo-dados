// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetaCreativeStudio from "./MetaCreativeStudio";
import type { CalendarItem } from "../../app/studio";
import type { AdPayload } from "../../app/metaAds";
import { listLibrary, uploadLibraryFile } from "../../app/library";

const shopApi = vi.hoisted(() => ({ searchShopProducts: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...shopApi }));
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
  it("carrossel: marca várias imagens em ordem, cada cartão com título, e mostra 1/2 na prévia", async () => {
    let latest = ad();
    function Host() {
      const [value, setValue] = useState<AdPayload["ad"]>({ ...ad(), format: "carousel", cards: [] });
      latest = value;
      return <MetaCreativeStudio clientId="roove" month="2026-11" calendar={calendar} ad={value} onChoose={(p) => setValue((v) => ({ ...v, ...p }))} />;
    }
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => root.render(<Host />));
    await act(async () => {});
    const pick = (title: string) => [...host.querySelectorAll("button")].find((b) => b.title === title) as HTMLButtonElement;
    await act(async () => pick("Arte calendário").click());
    await act(async () => pick("Arte da Roove").click());
    expect(latest.cards?.map((c) => c.image_url)).toEqual(["https://cdn.example.org/calendar.jpg", "https://cdn.example.org/roove.jpg"]);
    expect(pick("Arte da Roove").querySelector(".metaCreativeOrder")?.textContent).toBe("2");
    expect(host.querySelector(".metaCreativeSlideCount")?.textContent).toBe("1/2");
    const up = host.querySelector('[aria-label="Mover imagem 2 para antes"]') as HTMLButtonElement;
    await act(async () => up.click());
    expect(latest.cards?.[0].image_url).toBe("https://cdn.example.org/roove.jpg");
    expect(latest.image_url).toBe("https://cdn.example.org/roove.jpg");
    await act(async () => pick("Arte da Roove").click());
    expect(latest.cards?.length).toBe(1);
    act(() => root.unmount());
  });

  it("puxa produtos da loja e preenche título, preço e link do anúncio", async () => {
    shopApi.searchShopProducts.mockResolvedValue({ products: [{ product_id: "5", name: "Legging Preta", image_url: "https://cdn.example.org/legging.jpg",
      sku: "SKU1", review_status: "approved", variants: [], url: "https://roove.com.br/legging", price: "R$ 199,00" }] });
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), choose = vi.fn();
    await act(async () => {
      root.render(<MetaCreativeStudio clientId="roove" month="2026-11" calendar={calendar} ad={{ ...ad(), headline: "", link: "", description: "" }} onChoose={choose} />);
    });
    const origin = [...host.querySelectorAll("select")].find((s) => [...s.options].some((o) => o.value === "shop"))!;
    await act(async () => { origin.value = "shop"; origin.dispatchEvent(new Event("change", { bubbles: true })); });
    await act(async () => {});
    expect(shopApi.searchShopProducts).toHaveBeenCalledWith("");
    const product = [...host.querySelectorAll("button")].find((b) => b.title === "Legging Preta")!;
    expect(product.textContent).toContain("R$ 199,00");
    await act(async () => product.click());
    expect(choose).toHaveBeenCalledWith(expect.objectContaining({ image_url: "https://cdn.example.org/legging.jpg",
      headline: "Legging Preta", link: "https://roove.com.br/legging", description: "R$ 199,00" }));
    act(() => root.unmount());
  });
});
