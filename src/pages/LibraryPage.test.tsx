// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listLibrary: vi.fn(), addLibraryLink: vi.fn(), deleteLibraryItem: vi.fn(), uploadLibraryFile: vi.fn() }));
vi.mock("../app/library", async (original) => ({ ...(await original<typeof import("../app/library")>()), ...api }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ controls }: { controls?: React.ReactNode }) => <div>{controls}</div> }));

import LibraryPage from "./LibraryPage";

const LOGO = { id: "l1", kind: "arquivo", category: "logo", title: "Logo.png", url: "https://s/studio-library/ruah/a.png", mime_type: "image/png",
  side: "mugo", can_delete: true, size_bytes: 20480 };
const DOC = { id: "l2", kind: "link", category: "referencia", title: "Moodboard", url: "https://www.figma.com/file/x", side: "cliente", can_delete: false };
const POST = { id: "post-i1-0", kind: "post", category: "aprovado", title: "Post de Natal", url: "https://s/arte.jpg", side: "mugo", permalink: "https://instagram.com/p/x" };

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  api.listLibrary.mockResolvedValue({ items: [LOGO, DOC], approved: [POST], categories: {}, team: true });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.startsWith(label)) as HTMLButtonElement;
const show = async () => { await act(async () => { root.render(<LibraryPage />); }); await act(async () => {}); };
const type = async (el: HTMLInputElement, value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
});

describe("Biblioteca", () => {
  it("mostra materiais e posts aprovados, filtra por categoria e seção", async () => {
    await show();
    expect(host.querySelectorAll(".libCard")).toHaveLength(3);
    await act(async () => { btn("Logo").click(); });
    expect([...host.querySelectorAll(".libCard b")].map((b) => b.textContent)).toEqual(["Logo.png"]);
    await act(async () => { btn("Posts aprovados").click(); });
    expect([...host.querySelectorAll(".libCard b")].map((b) => b.textContent)).toEqual(["Post de Natal"]);
  });

  it("cola um link e ele entra na lista", async () => {
    api.addLibraryLink.mockResolvedValue({ item: { ...DOC, id: "l3", title: "Drive de fotos", url: "https://drive.google.com/x", category: "foto" } });
    await show();
    await act(async () => { btn("Adicionar link").click(); });
    await type(host.querySelector('input[aria-label="Link"]') as HTMLInputElement, "https://drive.google.com/x");
    await act(async () => { btn("Salvar link").click(); });
    expect(api.addLibraryLink).toHaveBeenCalledWith({ url: "https://drive.google.com/x", title: undefined, category: "referencia", note: undefined });
    expect(host.textContent).toContain("Drive de fotos");
  });

  it("abre o arquivo e só apaga o que pode", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    api.deleteLibraryItem.mockResolvedValue({ ok: true });
    await show();
    await act(async () => { (host.querySelector('[aria-label="Abrir Moodboard"]') as HTMLButtonElement).click(); });
    expect(host.querySelector(".libViewer")).toBeTruthy();
    expect(btn("Apagar")).toBeUndefined();
    await act(async () => { btn("Fechar").click(); });
    await act(async () => { (host.querySelector('[aria-label="Abrir Logo.png"]') as HTMLButtonElement).click(); });
    await act(async () => { btn("Apagar").click(); });
    expect(api.deleteLibraryItem).toHaveBeenCalledWith("l1");
    expect(host.textContent).not.toContain("Logo.png");
  });
});
