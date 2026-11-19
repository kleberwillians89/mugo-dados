// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReelsOptions from "./ReelsOptions";
import { formatOffset, frameSrc, isJpeg } from "./reelsOptions.helpers";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

const VID = "https://x.supabase.co/storage/v1/object/public/ig-media/a.mp4";
const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === text)!;

describe("ReelsOptions", () => {
  it("formata o momento e monta o link do frame", () => {
    expect(formatOffset(3500)).toBe("0:03,5");
    expect(formatOffset(75_000)).toBe("1:15,0");
    expect(frameSrc(`${VID}#t=1`, 7000)).toBe(`${VID}#t=7.0`);
    expect(isJpeg("https://a.com/capa.JPG?x=1")).toBe(true);
    expect(isJpeg("https://drive.google.com/file/d/abc123/view")).toBe(true);
    expect(isJpeg("https://a.com/capa.png")).toBe(false);
  });

  it("começa no frame, Feed ligado e sem teste; troca para imagem", async () => {
    const onChange = vi.fn();
    await act(async () => { root.render(<ReelsOptions value={{}} onChange={onChange} videoUrl={VID} itemId="i" />); });
    expect(button("Frame do vídeo").getAttribute("aria-pressed")).toBe("true");
    const [feed, trial] = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(feed.checked).toBe(true);
    expect(trial.checked).toBe(false);
    expect(host.textContent).toContain("primeiro frame, até você escolher");
    await act(async () => { button("Imagem de capa").click(); });
    expect(onChange).toHaveBeenLastCalledWith({ cover_mode: "image" });
    await act(async () => { trial.click(); });
    expect(onChange).toHaveBeenLastCalledWith({ trial: "manual" });
  });

  it("recusa capa em PNG por link e pede o vídeo quando não há", async () => {
    const onChange = vi.fn();
    await act(async () => { root.render(<ReelsOptions value={{ cover_mode: "image" }} onChange={onChange} videoUrl={null} itemId={null} />); });
    const input = host.querySelector<HTMLInputElement>('input[aria-label="Link da capa"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "https://a.com/capa.png");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { button("Usar link").click(); });
    expect(onChange).not.toHaveBeenCalled();
    expect(host.textContent).toContain("só aceita capa em JPG");
    await act(async () => { root.render(<ReelsOptions value={{ cover_mode: "frame" }} onChange={onChange} videoUrl={null} itemId={null} />); });
    expect(host.textContent).toContain("Envie o vídeo do Reels");
  });
});
