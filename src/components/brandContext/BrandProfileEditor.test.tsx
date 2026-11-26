// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({ getBrandProfile: vi.fn(), saveBrandProfile: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));
vi.mock("../Drawer", () => ({ default: ({ open, children }: { open: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null) }));

import BrandProfileEditor from "./BrandProfileEditor";
import { BRAND_PROFILE_SAVED } from "../../app/studio";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const profile = { tone_of_voice: "Leve", personality: "", audience: "", restrictions: "", visual_identity: "",
  pillars: [{ name: "Produto", weight: 60, description: "" }], keywords_use: [], keywords_avoid: [], hashtags: [], posts_per_week: 3,
  editorial_platforms: ["instagram"], posts_per_week_by_platform: {}, formats_enabled: ["reels"], custom_dates: [], content_language: "pt-BR" };

beforeEach(() => {
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  studio.getBrandProfile.mockResolvedValue({ profile, saved: true });
  studio.saveBrandProfile.mockImplementation(async (p) => ({ profile: p }));
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

describe("BrandProfileEditor", () => {
  it("usa os campos do Calendário, avisa a soma dos pesos e salva no mesmo endpoint", async () => {
    const saved = vi.fn();
    window.addEventListener(BRAND_PROFILE_SAVED, saved);
    const onClose = vi.fn();
    await act(async () => { root.render(<BrandProfileEditor open onClose={onClose} />); });
    await act(async () => {});
    expect(host.textContent).toContain("Tom de voz");
    expect(host.textContent).toContain("Plataformas do planejamento editorial");
    expect(host.textContent).toContain("somam 60%");
    const tone = host.querySelector("textarea")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(tone, "Acolhedor");
      tone.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(studio.saveBrandProfile).toHaveBeenCalledWith(expect.objectContaining({ tone_of_voice: "Acolhedor", pillars: profile.pillars }));
    expect(saved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
    window.removeEventListener(BRAND_PROFILE_SAVED, saved);
  });

  it("erro ao salvar fica na tela", async () => {
    studio.saveBrandProfile.mockRejectedValue(new Error("Perfil sem permissão para alterar esta empresa."));
    const onClose = vi.fn();
    await act(async () => { root.render(<BrandProfileEditor open onClose={onClose} />); });
    await act(async () => {});
    await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("sem permissão");
    expect(onClose).not.toHaveBeenCalled();
  });
});
