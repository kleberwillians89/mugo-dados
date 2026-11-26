// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { EmailDesign } from "../../app/emailMarketing";
import BlockEditor from "./BlockEditor";

const http = vi.hoisted(() => vi.fn());
vi.mock("../../app/api", () => ({ http }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function Editor() {
  const [design, setDesign] = useState<EmailDesign>({
    blocks: [{ type: "imagem", alt: "Curadoria de vinhos", href: "https://shop.example/oferta" }],
  });
  return <BlockEditor design={design} onChange={setDesign} allowImageUpload />;
}

it("vincula a imagem ao bloco e preserva texto alternativo, URL manual e link ao clicar", async () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const url = "https://storage.example/email/vinhos.png";
  http.mockResolvedValue({ url });

  try {
    await act(async () => root.render(<Editor />));
    const upload = host.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File(["mock"], "vinhos.webp", { type: "image/webp" });
    Object.defineProperty(upload, "files", { value: [file] });
    await act(async () => upload.dispatchEvent(new Event("change", { bubbles: true })));

    expect(http).toHaveBeenCalledWith("/api/email/images", expect.objectContaining({ method: "POST", body: file }));
    expect(host.querySelector("img")?.getAttribute("src")).toBe(url);
    expect(host.querySelector("img")?.alt).toBe("Curadoria de vinhos");
    expect(host.querySelector<HTMLInputElement>('[aria-label="Link ao clicar"]')?.value).toBe("https://shop.example/oferta");
    const manualUrl = host.querySelector<HTMLInputElement>('[aria-label="Link da imagem (https)"]')!;
    expect(manualUrl.value).toBe(url);
    expect(manualUrl.disabled).toBe(false);
    expect(host.textContent).toContain("Substituir imagem");

    const remove = [...host.querySelectorAll("button")].find((button) => button.textContent === "Remover imagem")!;
    await act(async () => remove.click());
    expect(host.querySelector("img")).toBeNull();
    expect(manualUrl.value).toBe("");
    expect(host.textContent).toContain("Enviar imagem");
  } finally {
    await act(async () => root.unmount());
  }
});
