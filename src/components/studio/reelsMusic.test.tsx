// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ searchReelsAudio: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...api }));

import ReelsMusicPicker from "./ReelsMusicPicker";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim().startsWith(text))!;

const HIT = { audio_id: "587", title: "Hit do verão", artist: "Banda", duration_ms: 95000, cover: "https://c/1.jpg", preview_url: null, type: "music" };

describe("Música do Reels", () => {
  it("abre com as músicas em alta e escolhe uma com volumes padrão", async () => {
    api.searchReelsAudio.mockResolvedValue({ audio: [HIT] });
    const onChange = vi.fn();
    await act(async () => { root.render(<ReelsMusicPicker onChange={onChange} />); });
    await act(async () => { button("Escolher música do Instagram").click(); });
    await act(async () => {});
    expect(api.searchReelsAudio).toHaveBeenCalledWith("", "music");
    expect(host.textContent).toContain("Banda · 1:35");
    await act(async () => { button("Usar").click(); });
    expect(onChange).toHaveBeenCalledWith({ audio_id: "587", title: "Hit do verão", artist: "Banda", cover: "https://c/1.jpg",
      audio_volume: 100, video_volume: 30 });
  });

  it("mostra a música escolhida e tira", async () => {
    const onChange = vi.fn();
    await act(async () => { root.render(<ReelsMusicPicker value={{ audio_id: "587", title: "Hit do verão", audio_volume: 80, video_volume: 20 }} onChange={onChange} />); });
    expect(host.textContent).toContain("Volume da música 80%");
    await act(async () => { (host.querySelector('[aria-label="Tirar a música"]') as HTMLButtonElement).click(); });
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("explica quando a Meta não libera a busca", async () => {
    api.searchReelsAudio.mockRejectedValue(new Error("A Meta não liberou a busca de músicas: permissão"));
    await act(async () => { root.render(<ReelsMusicPicker onChange={vi.fn()} />); });
    await act(async () => { button("Escolher música do Instagram").click(); });
    await act(async () => {});
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("não liberou");
  });

  it("buscar não envia o formulário do modal (não recarrega a página)", async () => {
    api.searchReelsAudio.mockResolvedValue({ audio: [HIT] });
    const onSubmit = vi.fn((e: Event) => e.preventDefault());
    const form = document.createElement("form"); form.addEventListener("submit", onSubmit); host.appendChild(form);
    const inner = createRoot(form);
    await act(async () => { inner.render(<ReelsMusicPicker onChange={vi.fn()} />); });
    await act(async () => { [...form.querySelectorAll("button")].find((b) => b.textContent?.includes("Escolher música"))!.click(); });
    await act(async () => {});
    expect(form.querySelector("form")).toBeNull();
    const input = form.querySelector('input[aria-label="Buscar música"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "djavan");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { [...form.querySelectorAll("button")].find((b) => b.textContent?.includes("Buscar"))!.click(); });
    await act(async () => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(api.searchReelsAudio).toHaveBeenCalledWith("djavan", "music");
    act(() => inner.unmount());
  });

  it("em Stories avisa que a música vai à mão e esconde os volumes", async () => {
    await act(async () => { root.render(<ReelsMusicPicker format="stories" value={{ audio_id: "587", title: "Hit do verão", audio_volume: 80, video_volume: 20 }} onChange={vi.fn()} />); });
    expect(host.textContent).not.toContain("Volume da música");
    expect(host.textContent).toContain("publicar à mão");
  });
});
