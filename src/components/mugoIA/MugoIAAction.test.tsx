// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ createFromMugoIA: vi.fn() }));
vi.mock("../../app/studio", async (original) => ({ ...(await original<typeof import("../../app/studio")>()), ...api }));
const nav = vi.hoisted(() => ({ openAppRoute: vi.fn() }));
vi.mock("../../app/routes", async (original) => ({ ...(await original<typeof import("../../app/routes")>()), ...nav }));
import MugoIAAction from "./MugoIAAction";
import type { MugoIAAction as Action } from "../../app/studio";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

const EMAIL: Action = { tipo: "email", status: "proposta", titulo: "BF Roove", pedido: "E-mail de Black Friday",
  assunto: "A Black Friday chegou", preheader: "Só até domingo", email_texto: "Oi", botao: "Ver" };

describe("proposta da Mugô IA", () => {
  it("mostra o que será criado e cria o rascunho com um clique", async () => {
    const created: Action = { ...EMAIL, status: "criado", criado: { id: "c1", name: "BF Roove", route: "email_marketing", label: "E-mail Marketing" } };
    api.createFromMugoIA.mockResolvedValue({ ok: true, acao: created, already: false });
    const onChange = vi.fn();
    await act(async () => root.render(<MugoIAAction messageId="m1" action={EMAIL} canCreate onChange={onChange} />));
    expect(host.textContent).toContain("A Black Friday chegou");
    expect(host.textContent).toContain("Nada é enviado nem publicado");
    await act(async () => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Criar no E-mail Marketing"))!.click());
    expect(api.createFromMugoIA).toHaveBeenCalledWith("m1", 0, undefined);
    expect(onChange).toHaveBeenCalledWith(created);
    await act(async () => root.render(<MugoIAAction messageId="m1" action={created} canCreate onChange={onChange} />));
    expect(host.textContent).toContain("Rascunho criado em E-mail Marketing: BF Roove");
    await act(async () => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Abrir"))!.click());
    expect(nav.openAppRoute).toHaveBeenCalledWith("email_marketing", "campanha=c1");  // abre a campanha, não só a tela
  });

  it("pacote: cada peça tem o seu Criar; WhatsApp vai para aprovação da Meta e abre em Modelos", async () => {
    const { default: MugoIAActions } = await import("./MugoIAActions");
    const wa: Action = { tipo: "whatsapp_modelo", status: "proposta", titulo: "Convite grupo", pedido: "", wa_corpo: "Oi {{1}}, o First Access abriu!", wa_nome: "convite_grupo_11251622" };
    const done: Action = { ...wa, status: "criado", criado: { id: "t1", name: "convite_grupo_11251622", route: "whatsapp", label: "WhatsApp · Modelos (aguardando aprovação da Meta)", status: "PENDING" } };
    api.createFromMugoIA.mockResolvedValue({ ok: true, acao: done, item: 1, already: false });
    const onMeta = vi.fn();
    await act(async () => root.render(<MugoIAActions messageId="m1" meta={{ acoes: [EMAIL, wa] }} canCreate onMeta={onMeta} />));
    expect(host.textContent).toContain("2 peças para criar");
    expect(host.textContent).toContain("Oi {{1}}, o First Access abriu!");
    expect(host.textContent).toContain("Sem link, o modelo vai sem botão.");
    const link = host.querySelector<HTMLInputElement>('input[inputmode="url"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(link, "https://chat.whatsapp.com/abc");
      link.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Enviar para aprovação da Meta"))!.click());
    expect(api.createFromMugoIA).toHaveBeenCalledWith("m1", 1, { wa_botao_url: "https://chat.whatsapp.com/abc", wa_botao_texto: "Entrar no grupo" });
    expect(onMeta).toHaveBeenCalledWith({ acoes: [EMAIL, done] });
    await act(async () => root.render(<MugoIAActions messageId="m1" meta={{ acoes: [EMAIL, done] }} canCreate onMeta={onMeta} />));
    expect(host.textContent).toContain("Enviado para aprovação da Meta");
    await act(async () => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("Abrir"))!.click());
    expect(nav.openAppRoute).toHaveBeenCalledWith("whatsapp", undefined);
    expect(window.sessionStorage.getItem("mugo:whatsapp:area")).toBe("models");
    window.sessionStorage.clear();
  });

  it("campanha na Meta mostra verba e período; sem permissão não há botão", async () => {
    const meta: Action = { tipo: "campanha_meta", status: "proposta", titulo: "Leads BF", pedido: "x", objetivo: "leads", verba_diaria: 40, dias: 10 };
    await act(async () => root.render(<MugoIAAction messageId="m1" action={meta} canCreate={false} onChange={vi.fn()} />));
    expect(host.textContent).toContain("/dia · 10 dias");
    expect(host.querySelector("button")).toBeNull();
    expect(host.textContent).toContain("Quem administra a marca");
  });
});
