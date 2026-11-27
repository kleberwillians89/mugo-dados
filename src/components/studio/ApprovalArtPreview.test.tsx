// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import ApprovalArtPreview from "./ApprovalArtPreview";
import { approvalRatio } from "./artCarousel.helpers";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });
const render = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); };
const ratioOf = () => host.querySelector<HTMLElement>(".approvalMedia")!.style.getPropertyValue("--art-ratio");

describe("Prévia de aprovação sem cortes (briefing integrado, frente 5)", () => {
  it("proporção por formato: Stories/Reels 9:16 sem o limite do feed; feed segue a arte", () => {
    expect(approvalRatio("stories", 1080, 1080)).toBeCloseTo(9 / 16);
    expect(approvalRatio("reels")).toBeCloseTo(9 / 16);
    expect(approvalRatio("imagem", 1080, 1080)).toBe(1);
    expect(approvalRatio("carrossel", 1080, 1350)).toBeCloseTo(0.8);
    expect(approvalRatio("imagem", 1080, 1920)).toBeCloseTo(0.8); // vertical no feed: o Instagram mostra 4:5
    expect(approvalRatio("video", 1920, 1080)).toBeCloseTo(1920 / 1080);
    expect(approvalRatio("imagem")).toBeCloseTo(0.8);
  });

  it("desktop e mobile são molduras diferentes, e a moldura acompanha a arte carregada", async () => {
    await render(<ApprovalArtPreview slides={["https://x/a.jpg"]} format="imagem" mode="desktop" account="Roove" caption="Legenda" fallback="-" />);
    expect(host.querySelector(".approvalBrowser")).not.toBeNull();
    expect(host.querySelector(".approvalPhone")).toBeNull();
    expect(host.textContent).toContain("instagram.com/roove");
    const img = host.querySelector("img")!;
    Object.defineProperty(img, "naturalWidth", { value: 1080 }); Object.defineProperty(img, "naturalHeight", { value: 1080 });
    await act(async () => { img.dispatchEvent(new Event("load")); });
    expect(ratioOf()).toBe("1");
    await render(<ApprovalArtPreview slides={["https://x/a.jpg"]} format="imagem" mode="mobile" account="Roove" caption="Legenda" fallback="-" />);
    expect(host.querySelector(".approvalPhone")).not.toBeNull();
    expect(host.querySelector(".approvalBrowser")).toBeNull();
  });

  it("stories ocupa a tela 9:16 e 'Ver arte completa' abre o slide atual ampliado", async () => {
    await render(<ApprovalArtPreview slides={["https://x/a.jpg", "https://x/b.mp4"]} format="stories" mode="mobile" account="Roove" caption="" fallback="-" />);
    expect(Number(ratioOf())).toBeCloseTo(9 / 16);
    expect(host.querySelector(".approvalMedia.is-vertical")).not.toBeNull();
    await act(async () => { (host.querySelector('[aria-label="Próximo slide"]') as HTMLButtonElement).click(); });
    await act(async () => { (host.querySelector(".approvalFullButton") as HTMLButtonElement).click(); });
    const dialog = host.querySelector('[role="dialog"]')!;
    expect(dialog.getAttribute("aria-label")).toBe("Arte completa, slide 2 de 2");
    expect(dialog.querySelector("video")?.getAttribute("src")).toBe("https://x/b.mp4");
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(host.querySelector('[role="dialog"]')).toBeNull();
  });

  it("sem arte: mostra o texto da peça e não oferece ampliar", async () => {
    await render(<ApprovalArtPreview slides={[]} format="imagem" mode="desktop" account="Roove" caption="" fallback="Gancho do post" />);
    expect(host.textContent).toContain("Gancho do post");
    expect(host.querySelector(".approvalFullButton")).toBeNull();
  });
});
