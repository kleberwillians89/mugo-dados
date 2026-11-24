// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import MetaCreativeStudio from "./MetaCreativeStudio";
import type { CalendarItem } from "../../app/studio";
import type { AdPayload } from "../../app/metaAds";
import { uploadArt } from "../../app/artUpload";

const shopApi = vi.hoisted(() => ({ searchShopProducts: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...shopApi }));
vi.mock("../../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
vi.mock("../../app/artUpload", () => ({ uploadArt: vi.fn() }));
vi.mock("../../app/metaAds", async (original) => ({ ...(await original<typeof import("../../app/metaAds")>()),
  listInstagramCreativePosts: vi.fn().mockResolvedValue({ posts: [] }) }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const ad = (): AdPayload["ad"] => ({
  primary_text: "Black Friday Roove", headline: "Acesso antecipado",
  description: "Cupons especiais", cta: "SIGN_UP",
  link: "https://roove.com.br/black", image_url: "", calendar_item_id: null,
});
const calendar = [{ id: "post-1", title: "Arte calendário", art_url: "https://cdn.example.org/calendar.jpg" },
  { id: "post-2", title: "Arte da Roove", art_url: "https://cdn.example.org/roove.jpg" }] as CalendarItem[];
let host: HTMLDivElement;
afterEach(() => {host?.remove(); vi.clearAllMocks();});

describe("Mídia On — Estúdio de criativos", () => {
  it("não usa a Biblioteca: mostra artes do Calendário, seleção real e as três prévias de proporções", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), choose = vi.fn();
    await act(async () => {
      root.render(<MetaCreativeStudio clientId="roove" month="2026-11" calendar={calendar} ad={ad()} onChoose={choose} />);
    });
    await act(async () => {});
    expect(host.textContent).not.toContain("Biblioteca");
    expect(host.textContent).toContain("Arte da Roove");
    expect(host.textContent).toContain("Arte calendário");
    const gallery = [...host.querySelectorAll("button")].find((b) => b.title === "Arte da Roove");
    await act(async () => gallery?.click());
    expect(choose).toHaveBeenCalledWith({image_url:"https://cdn.example.org/roove.jpg",calendar_item_id:"post-2", media_type:"image", video_url:"",instagram_post_id:null});
    const story = [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Stories / Reels"));
    await act(async () => story?.click());
    expect(story?.getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector(".metaCreativeDevice")?.className).toContain("is-story");
    act(() => root.unmount());
  });
  it("envia a arte do anúncio direto, sem passar pela Biblioteca", async () => {
    vi.mocked(uploadArt).mockResolvedValue("https://cdn.example.org/new.jpg");
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), choose = vi.fn();
    await act(async () => root.render(<MetaCreativeStudio clientId="roove" month="2026-11"
      calendar={[]} ad={ad()} onChoose={choose} />));
    await act(async () => {});
    const input = host.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["test"], "criativo.png", {type:"image/png"});
    Object.defineProperty(input, "files", { configurable:true, value:[file] });
    await act(async () => input.dispatchEvent(new Event("change",{bubbles:true})));
    expect(uploadArt).toHaveBeenCalledWith(null, file);
    expect(choose).toHaveBeenCalledWith({image_url:"https://cdn.example.org/new.jpg",calendar_item_id:null, media_type:"image", video_url:"",instagram_post_id:null});
    expect(host.textContent).toContain("Enviada agora");
    act(() => root.unmount());
  });
  it("envia múltiplas imagens como anúncios separados sem substituir a imagem existente", async () => {
    vi.mocked(uploadArt).mockResolvedValueOnce("https://cdn.example.org/one.jpg")
      .mockResolvedValueOnce("https://cdn.example.org/two.jpg");
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), choose = vi.fn(), add = vi.fn();
    await act(async () => root.render(<MetaCreativeStudio clientId="roove" month="2026-11"
      calendar={[]} ad={{ ...ad(), image_url: "https://cdn.example.org/existing.jpg" }}
      onChoose={choose} availableAds={9} onAddCreatives={add} />));
    const input = host.querySelector('input[type="file"]') as HTMLInputElement;
    const files = [new File(["1"], "one.png", { type: "image/png" }),
      new File(["2"], "two.png", { type: "image/png" })];
    Object.defineProperty(input, "files", { configurable: true, value: files });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    expect(choose).not.toHaveBeenCalled();
    expect(add).toHaveBeenCalledTimes(1);
    expect(add).toHaveBeenCalledWith([
      expect.objectContaining({ image_url: "https://cdn.example.org/one.jpg", media_type: "image" }),
      expect.objectContaining({ image_url: "https://cdn.example.org/two.jpg", media_type: "image" }),
    ]);
    act(() => root.unmount());
  });
  it("rejeita lote acima da capacidade antes de enviar qualquer arquivo", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host), choose = vi.fn(), add = vi.fn();
    await act(async () => root.render(<MetaCreativeStudio clientId="roove" month="2026-11"
      calendar={[]} ad={{ ...ad(), image_url: "https://cdn.example.org/existing.jpg" }}
      onChoose={choose} availableAds={1} onAddCreatives={add} />));
    const input = host.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, "files", { configurable: true,
      value: [new File(["1"], "one.png", { type: "image/png" }), new File(["2"], "two.png", { type: "image/png" })] });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    expect(host.textContent).toContain("Restam 1 espaços");
    expect(uploadArt).not.toHaveBeenCalled();
    expect(add).not.toHaveBeenCalled();
    act(() => root.unmount());
  });

  it("carrossel: marca várias imagens em ordem, cada cartão com título, e mostra 1/2 na prévia", async () => {
    const seen: AdPayload["ad"][] = [];
    function Host() {
      const [value, setValue] = useState<AdPayload["ad"]>({ ...ad(), format: "carousel", cards: [] });
      seen.push(value);
      return <MetaCreativeStudio clientId="roove" month="2026-11" calendar={calendar} ad={value} onChoose={(p) => setValue((v) => ({ ...v, ...p }))} />;
    }
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => root.render(<Host />));
    await act(async () => {});
    const pick = (title: string) => [...host.querySelectorAll("button")].find((b) => b.title === title) as HTMLButtonElement;
    await act(async () => pick("Arte calendário").click());
    await act(async () => pick("Arte da Roove").click());
    expect(seen[seen.length - 1].cards?.map((c) => c.image_url)).toEqual(["https://cdn.example.org/calendar.jpg", "https://cdn.example.org/roove.jpg"]);
    expect(pick("Arte da Roove").querySelector(".metaCreativeOrder")?.textContent).toBe("2");
    expect(host.querySelector(".metaCreativeSlideCount")?.textContent).toBe("1/2");
    const up = host.querySelector('[aria-label="Mover imagem 2 para antes"]') as HTMLButtonElement;
    await act(async () => up.click());
    expect(seen[seen.length - 1].cards?.[0].image_url).toBe("https://cdn.example.org/roove.jpg");
    expect(seen[seen.length - 1].image_url).toBe("https://cdn.example.org/roove.jpg");
    await act(async () => pick("Arte da Roove").click());
    expect(seen[seen.length - 1].cards?.length).toBe(1);
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
