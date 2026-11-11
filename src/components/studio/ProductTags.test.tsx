// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({ getShop: vi.fn(), searchShopProducts: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...studio }));

import ProductTags from "./ProductTags";

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;

describe("Produtos da loja no post", () => {
  it("busca no catálogo e marca o produto no slide escolhido", async () => {
    studio.getShop.mockResolvedValue({ ready: true, eligible: true, catalogs: [{ id: "9", name: "Roove", shop_name: "Roove", product_count: 10 }], missing_scopes: [], message: null });
    studio.searchShopProducts.mockResolvedValue({ products: [{ product_id: "5", name: "Legging Preta", image_url: "https://img/5.jpg", sku: "SKU1", review_status: "approved", variants: [] }] });
    const onChange = vi.fn();
    await act(async () => { root.render(<ProductTags value={[]} onChange={onChange} format="carrossel" slides={["https://cdn/1.jpg", "https://cdn/2.jpg"]} />); });
    await act(async () => { btn("Marcar produtos da loja").click(); });
    const select = host.querySelector(".productTagSlide select") as HTMLSelectElement;
    await act(async () => { select.value = "1"; select.dispatchEvent(new Event("change", { bubbles: true })); });
    const input = host.querySelector('input[aria-label="Buscar produto da loja"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "legging");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { btn("Buscar").click(); });
    expect(studio.searchShopProducts).toHaveBeenCalledWith("legging", "9");
    const product = [...host.querySelectorAll(".productResults button")][0] as HTMLButtonElement;
    await act(async () => { product.click(); });
    expect(onChange).toHaveBeenCalledWith([{ product_id: "5", name: "Legging Preta", image_url: "https://img/5.jpg", slide: 1, x: 0.5, y: 0.5 }]);
  });

  it("loja não liberada mostra o motivo; Stories não aceitam", async () => {
    studio.getShop.mockResolvedValue({ ready: false, eligible: false, catalogs: [], missing_scopes: [], message: "Esta conta do Instagram não está liberada para marcar produtos." });
    await act(async () => { root.render(<ProductTags value={[]} onChange={() => undefined} format="imagem" slides={[]} />); });
    await act(async () => { btn("Marcar produtos da loja").click(); });
    expect(host.textContent).toContain("não está liberada para marcar produtos");
    await act(async () => { root.render(<ProductTags value={[]} onChange={() => undefined} format="stories" slides={[]} />); });
    expect(host.textContent).toContain("Stories não aceitam produto marcado");
  });
});
