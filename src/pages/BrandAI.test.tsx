// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({ getBrandProfile: vi.fn() }));
vi.mock("../app/studio", async (original) => ({ ...(await original<typeof import("../app/studio")>()), ...studio }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));
// Os componentes reaproveitados têm testes próprios: aqui só conferimos que a página os monta com a permissão certa.
vi.mock("../components/studio/BrandKnowledge", () => ({ default: ({ canManage }: { canManage: boolean }) => <div data-testid="knowledge">{canManage ? "kb-edit" : "kb-read"}</div> }));
vi.mock("../components/brandContext/BrandProfileEditor", () => ({ default: ({ open }: { open: boolean }) => (open ? <div data-testid="profile-editor" /> : null) }));
vi.mock("../components/brandContext/BrandImport", () => ({ default: () => <div data-testid="import" /> }));
vi.mock("../components/studio/BrandAgent", () => ({ default: () => <div data-testid="agent" /> }));
vi.mock("../components/admin/BusinessContextPanel", () => ({ default: ({ canEdit }: { canEdit: boolean }) => <div data-testid="business">{canEdit ? "bc-edit" : "bc-read"}</div> }));

import BrandAI from "./BrandAI";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const profile = { tone_of_voice: "Leve e sensorial", personality: "Sofisticada", audience: "Mulheres 25-45", restrictions: "",
  pillars: [{ name: "Produto", weight: 50, description: "" }, { name: "Lifestyle", weight: 30, description: "" }],
  keywords_use: [], keywords_avoid: ["barato"], hashtags: [], visual_identity: "", posts_per_week: 4,
  editorial_platforms: ["instagram"], posts_per_week_by_platform: { instagram: 4 }, formats_enabled: ["reels", "carrossel"], custom_dates: [] };

beforeEach(() => {
  window.history.replaceState({}, "", "/contexto-da-marca");
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  studio.getBrandProfile.mockResolvedValue({ profile, saved: true });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); await act(async () => {}); };
const button = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === label)!;

describe("Contexto da Marca", () => {
  it("abre em Identidade e estratégia com o perfil e o contexto estratégico", async () => {
    await show(<BrandAI canManage isAgency />);
    expect(host.querySelector("h1")?.textContent).toBe("Contexto da Marca");
    expect(host.textContent).toContain("Leve e sensorial");
    expect(host.textContent).toContain("Os pesos somam 80%");  // avisa, não normaliza
    expect(host.querySelector('[data-testid="business"]')?.textContent).toBe("bc-edit");
    expect(button("Editar perfil")).toBeTruthy();
    expect(button("Sugerir com IA")).toBeTruthy();  // sugestão da IA: só equipe Mugô
  });

  it("leitor só consulta: sem edição, sem upload e sem atalhos de administração", async () => {
    await show(<BrandAI canManage={false} />);
    expect(host.querySelector('[data-testid="business"]')?.textContent).toBe("bc-read");
    expect(button("Editar perfil")).toBeUndefined();
    expect(host.querySelector('[data-testid="profile-editor"]')).toBeNull();
    await act(async () => { button("Documentos e conhecimento").click(); });
    expect(host.querySelector('[data-testid="knowledge"]')?.textContent).toBe("kb-read");
    expect(host.querySelector('[data-testid="import"]')).toBeNull();  // leitor não importa
    await act(async () => { button("Configuração operacional").click(); });
    expect(host.textContent).toContain("Calendário e perfil editorial");
    expect(host.textContent).not.toContain("Integrações");
    expect(host.textContent).not.toContain("Usuários e acessos");
  });

  it("admin do cliente edita perfil, contexto e documentos da própria empresa", async () => {
    await show(<BrandAI canManage />);
    expect(host.querySelector('[data-testid="business"]')?.textContent).toBe("bc-edit");
    expect(button("Sugerir com IA")).toBeUndefined();
    await act(async () => { button("Editar perfil").click(); });
    expect(host.querySelector('[data-testid="profile-editor"]')).not.toBeNull();
    await act(async () => { button("Importar do planejamento").click(); });
    expect(host.querySelector('[data-testid="import"]')).not.toBeNull();
    await act(async () => { button("Identidade e estratégia").click(); });
    await act(async () => { button("Documentos e conhecimento").click(); });
    expect(host.querySelector('[data-testid="knowledge"]')?.textContent).toBe("kb-edit");
    expect(host.querySelector('[data-testid="import"]')).not.toBeNull();
    expect(window.location.search).toBe("?aba=documentos");
  });

  it("atalho operacional troca de tela pelo endereço, sem formulário duplicado", async () => {
    const pop = vi.fn();
    window.addEventListener("popstate", pop);
    await show(<BrandAI canManage isAgency />);
    await act(async () => { button("Configuração operacional").click(); });
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".bcShortcut button")[0].click(); });
    expect(window.location.pathname).toBe("/social-media");
    expect(pop).toHaveBeenCalled();
    window.removeEventListener("popstate", pop);
  });

  it("abre direto na aba pedida no endereço", async () => {
    window.history.replaceState({}, "", "/ia-da-marca?aba=documentos");
    await show(<BrandAI canManage />);
    expect(host.querySelector('[data-testid="knowledge"]')).not.toBeNull();
  });
});
