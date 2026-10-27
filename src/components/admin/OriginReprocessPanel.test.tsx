// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ previewOriginReprocess: vi.fn(), applyOriginReprocess: vi.fn() }));
vi.mock("../../app/api", () => api);

import OriginReprocessPanel from "./OriginReprocessPanel";
import type { PlatformCompany } from "../../app/api";

const COMPANIES = [{ id: "cura", name: "Curavino", status: "active" }] as unknown as PlatformCompany[];
let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

const button = (label: string) =>
  Array.from(container.querySelectorAll("button")).find((item) => item.textContent === label) as HTMLButtonElement;

describe("OriginReprocessPanel", () => {
  it("mostra a prévia e só grava depois de confirmar", async () => {
    api.previewOriginReprocess.mockResolvedValue({ ok: true, client_id: "cura", dry_run: true, providers: {
      fbits: { scanned_without_origin: 50, origin_found: 12, updated: 0, by_channel: { "paid_search:click_id": 12 } },
      shopify: { scanned_without_origin: 0, origin_found: 0, updated: 0, by_channel: {} },
    } });
    api.applyOriginReprocess.mockResolvedValue({ ok: true, client_id: "cura", dry_run: false, providers: {
      fbits: { scanned_without_origin: 50, origin_found: 12, updated: 12, by_channel: { "paid_search:click_id": 12 } },
    } });
    await act(async () => root.render(<OriginReprocessPanel companies={COMPANIES} />));
    await act(async () => button("Analisar pedidos sem origem").click());
    expect(api.previewOriginReprocess).toHaveBeenCalledWith("cura");
    const result = container.querySelector('[data-testid="origin-reprocess-result"]')?.textContent || "";
    expect(result).toContain("50 pedido(s) sem origem; 12 com origem encontrada");
    expect(result).toContain("Google Ads (clique de anúncio, sem campanha): 12");
    expect(api.applyOriginReprocess).not.toHaveBeenCalled();
    await act(async () => button("Aplicar origem encontrada").click());
    await act(async () => button("Confirmar atualização").click());
    expect(api.applyOriginReprocess).toHaveBeenCalledWith("cura");
    expect(container.textContent).toContain("12 pedido(s) atualizados");
  });

  it("sem origem nova não oferece aplicar", async () => {
    api.previewOriginReprocess.mockResolvedValue({ ok: true, client_id: "cura", dry_run: true, providers: {
      fbits: { scanned_without_origin: 50, origin_found: 0, updated: 0, by_channel: {} },
    } });
    await act(async () => root.render(<OriginReprocessPanel companies={COMPANIES} />));
    await act(async () => button("Analisar pedidos sem origem").click());
    expect(container.textContent).toContain("Nenhuma origem nova encontrada");
    expect(button("Aplicar origem encontrada")).toBeUndefined();
  });
});
