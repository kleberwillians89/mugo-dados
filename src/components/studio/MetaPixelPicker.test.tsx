// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const m = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("../../app/metaAds", () => ({ readAdPixels: m.read }));
import MetaPixelPicker from "./MetaPixelPicker";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });

describe("Escolher o pixel na revisão", () => {
  it("começa no recomendado e deixa trocar", async () => {
    m.read.mockResolvedValue({ current: "111", recommended: "222", pixels: [
      { id: "111", name: "https://roove.com.br", last_fired_time: null, active: false, unavailable: false },
      { id: "222", name: "Roove Web Official", last_fired_time: new Date().toISOString(), active: true, unavailable: false }] });
    const onChange = vi.fn();
    host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => createRoot(host).render(<MetaPixelPicker draftId="d1" value={null} onChange={onChange} />));
    await act(async () => {});
    expect(onChange).toHaveBeenCalledWith("222");
    const select = host.querySelector("select") as HTMLSelectElement;
    expect(select.value).toBe("222");
    expect(select.textContent).toContain("(recomendado)");
  });
});
