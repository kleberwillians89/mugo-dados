// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const auth = vi.hoisted(() => ({
  getSession: vi.fn(),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  resetPasswordForEmail: vi.fn(),
  updateUser: vi.fn(),
}));

vi.mock("../app/supabase", () => ({
  supabase: { auth },
  getSupabaseBootstrapError: () => null,
  isLocalAuthAvailable: () => false,
  enableLocalAuth: vi.fn(),
}));

import Login from "./Login";
import { LEGAL_CONTACT } from "../app/legalContact";

describe("Login — produto, frase e formulário", () => {
  it("não mostra clientes nem logos de terceiros", () => {
    const markup = renderToStaticMarkup(<Login />);
    expect(markup).toContain("Mugô Dados");
    expect(markup).toContain("Dados claros.");
    expect(markup).toContain("Decisões melhores.");
    expect(markup).toContain("Acesse sua conta");
    expect(markup).toContain('<label for="email">E-mail</label>');
    expect(markup).toContain('<label for="password">Senha</label>');
    expect(markup).toContain(">Entrar</button>");
    expect(markup).toContain("Esqueci minha senha");
    expect(markup).not.toContain("/clients/");
    expect(markup).not.toContain("/platforms/");
    // Nenhum e-mail real como exemplo no campo.
    expect(markup).not.toContain("mugo.agencia@gmail.com");
  });

  it("traz consentimento e acesso visível às páginas legais e ao contato de privacidade", () => {
    const markup = renderToStaticMarkup(<Login />);
    expect(markup).toContain("Ao continuar, você concorda com os");
    expect(markup).toContain('href="/termos-de-uso"');
    expect(markup).toContain('href="/privacidade"');
    expect(markup).toContain('href="/protecao-de-dados"');
    expect(markup).toContain(`href="mailto:${LEGAL_CONTACT}"`);
    // Redação do aceite marcada como pendente de validação jurídica; nenhuma promessa de conformidade.
    expect(markup).toContain('class="loginConsent" data-legal-status="review-pending"');
    expect(markup).not.toMatch(/LGPD compliant|100%|em conformidade com a LGPD/i);
  });
});

describe("Login — fluxo preservado", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    vi.clearAllMocks();
    auth.getSession.mockResolvedValue({ data: { session: null }, error: null });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function type(selector: string, value: string) {
    const input = container.querySelector(selector) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setter?.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  async function submit() {
    const form = container.querySelector("form") as HTMLFormElement;
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
  }

  it("entra com Supabase Auth e entrega a sessão ao App", async () => {
    const session = { access_token: "fake-access-token-not-real", user: { id: "user-1", email: "ana@exemplo.com.br" } };
    auth.signInWithPassword.mockResolvedValue({ data: { session }, error: null });
    const onSuccess = vi.fn();
    await act(async () => root.render(<Login onPasswordLoginSuccess={onSuccess} />));
    await type("#email", " ana@exemplo.com.br ");
    await type("#password", "senha-de-teste");
    await submit();
    expect(auth.signInWithPassword).toHaveBeenCalledWith({ email: "ana@exemplo.com.br", password: "senha-de-teste" });
    expect(onSuccess).toHaveBeenCalledWith(session);
  });

  it("credencial inválida: mensagem em português, sem nomes internos de infraestrutura", async () => {
    auth.signInWithPassword.mockResolvedValue({ data: { session: null }, error: new Error("Invalid login credentials") });
    await act(async () => root.render(<Login />));
    await type("#email", "ana@exemplo.com.br");
    await type("#password", "errada");
    await submit();
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toBe("E-mail ou senha incorretos.");
    expect(container.textContent).not.toContain("Supabase");
  });

  it("Esqueci minha senha envia o link de redefinição do Supabase", async () => {
    auth.resetPasswordForEmail.mockResolvedValue({ error: null });
    await act(async () => root.render(<Login />));
    const forgot = [...container.querySelectorAll("button")].find((button) => button.textContent === "Esqueci minha senha");
    await act(async () => forgot?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container.querySelector("h1")?.textContent).toBe("Redefinir senha");
    expect(container.querySelector("#password")).toBeNull();
    await type("#email", "ana@exemplo.com.br");
    await submit();
    expect(auth.resetPasswordForEmail).toHaveBeenCalledWith("ana@exemplo.com.br", {
      redirectTo: `${window.location.origin}/?type=recovery`,
    });
    expect(container.textContent).toContain("Se o e-mail estiver cadastrado, você receberá o link de redefinição.");
  });
});
