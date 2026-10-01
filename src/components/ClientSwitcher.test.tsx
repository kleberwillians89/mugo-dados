// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SUPABASE_AUTH_OPTIONS } from "../app/supabase";
import ClientSwitcher from "./ClientSwitcher";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("session and tenant controls", () => {
  it("keeps the Supabase-managed session persistent and renewable", () => {
    expect(SUPABASE_AUTH_OPTIONS).toEqual({
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    });
  });

  it("renders a single tenant as a static identity without a selector", () => {
    const markup = renderToStaticMarkup(
      <ClientSwitcher
        activeClientId="roove"
        clients={[{ client_id: "roove", name: "Roove", role: "platform_admin" }]}
        onChange={() => {}}
      />
    );
    expect(markup).toContain('aria-label="Empresa ativa: Roove"');
    expect(markup).not.toContain("<button");
    expect(markup).toContain("Roove");
    expect(markup).toContain("Empresa ativa");
  });

  it("keeps the selector in document flow and anchors its panel to it", () => {
    const cssPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../styles/shell.css");
    const css = readFileSync(cssPath, "utf8");
    expect(css).toMatch(/\.clientSwitcher\{[\s\S]*?position: relative;/);
    expect(css).toMatch(/\.clientSwitcherPanel\{[\s\S]*?position: absolute;[\s\S]*?top: calc\(100% \+ 6px\)/);
  });
});

describe("ClientSwitcher — dropdown premium (não é mais um select nativo)", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const clients = [
    { client_id: "amalie", name: "Amalie", role: "owner" },
    { client_id: "roove", name: "Roove", role: "viewer" },
    { client_id: "ruah", name: "RŪAH", role: "client_admin" },
    { client_id: "curavino", name: "Curavino", role: "client_admin" },
    { client_id: "santo-circuito", name: "Santo Circuito", role: "viewer" },
  ];

  it("abre a lista ao clicar no trigger e mostra todas as empresas", async () => {
    await act(async () => {
      root.render(<ClientSwitcher activeClientId="amalie" clients={clients} onChange={() => {}} />);
    });
    const trigger = container.querySelector(".clientSwitcherTrigger") as HTMLButtonElement;
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".clientSwitcherPanel")).toBeTruthy();
    expect(container.textContent).toContain("Roove");
    expect(container.textContent).toContain("RŪAH");
  });

  it("filtra empresas ao digitar na busca", async () => {
    await act(async () => {
      root.render(<ClientSwitcher activeClientId="amalie" clients={clients} onChange={() => {}} />);
    });
    const trigger = container.querySelector(".clientSwitcherTrigger") as HTMLButtonElement;
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const search = container.querySelector(".clientSwitcherSearch") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setter?.call(search, "roo");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const options = [...container.querySelectorAll(".clientSwitcherOption")];
    expect(options).toHaveLength(1);
    expect(options[0].textContent).toContain("Roove");
  });

  it("chama onChange e fecha o painel ao selecionar uma empresa", async () => {
    const onChange = vi.fn();
    await act(async () => {
      root.render(<ClientSwitcher activeClientId="amalie" clients={clients} onChange={onChange} />);
    });
    const trigger = container.querySelector(".clientSwitcherTrigger") as HTMLButtonElement;
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const rooveOption = [...container.querySelectorAll(".clientSwitcherOption")].find((el) =>
      el.textContent?.includes("Roove")
    ) as HTMLButtonElement;
    await act(async () => {
      rooveOption.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    });
    expect(onChange).toHaveBeenCalledWith("roove");
    expect(container.querySelector(".clientSwitcherPanel")).toBeNull();
  });
});

describe("ClientSwitcher — empresa ativa, teclado e popover", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const three = [
    { client_id: "vinhos", name: "Curavino", role: "agency_admin" },
    { client_id: "roove", name: "Roove", role: "agency_admin" },
    { client_id: "origami", name: "Origami", role: "agency_admin" },
  ];

  async function open() {
    const trigger = container.querySelector(".clientSwitcherTrigger") as HTMLButtonElement;
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    return trigger;
  }

  async function key(name: string) {
    await act(async () => {
      document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true }));
    });
  }

  it("mostra a marca da empresa ativa no gatilho e a marca como ativa na lista", async () => {
    await act(async () => root.render(<ClientSwitcher activeClientId="vinhos" clients={three} onChange={() => {}} />));
    const trigger = container.querySelector(".clientSwitcherTrigger") as HTMLButtonElement;
    expect(trigger.querySelector("img")?.getAttribute("src")).toBe("/clients/curavino.png");
    expect(trigger.querySelector(".clientSwitcherName")?.textContent).toBe("Curavino");
    await open();
    expect(container.querySelector(".clientSwitcherPanelTitle")?.textContent).toBe("Empresas");
    const selected = container.querySelectorAll('[role="option"][aria-selected="true"]');
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toBe("Curavino");
    expect(selected[0].querySelector(".clientSwitcherCheck")).toBeTruthy();
    // Com menos de 5 empresas a lista inteira cabe à vista: sem busca.
    expect(container.querySelector(".clientSwitcherSearch")).toBeNull();
  });

  it("teclado: setas percorrem a lista, Esc fecha e devolve o foco ao gatilho", async () => {
    await act(async () => root.render(<ClientSwitcher activeClientId="vinhos" clients={three} onChange={() => {}} />));
    const trigger = await open();
    expect(document.activeElement?.textContent).toBe("Curavino");
    await key("ArrowDown");
    expect(document.activeElement?.textContent).toBe("Roove");
    await key("End");
    expect(document.activeElement?.textContent).toBe("Origami");
    await key("ArrowDown");
    expect(document.activeElement?.textContent).toBe("Curavino");
    await key("Escape");
    expect(container.querySelector(".clientSwitcherPanel")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("ativar uma opção pelo teclado (Enter/Espaço = click no botão) troca a empresa", async () => {
    const onChange = vi.fn();
    await act(async () => root.render(<ClientSwitcher activeClientId="vinhos" clients={three} onChange={onChange} />));
    await open();
    await key("ArrowDown");
    await act(async () => {
      (document.activeElement as HTMLButtonElement).click();
    });
    expect(onChange).toHaveBeenCalledWith("roove");
    expect(container.querySelector(".clientSwitcherPanel")).toBeNull();
  });

  it("clique fora fecha o painel", async () => {
    await act(async () => root.render(<ClientSwitcher activeClientId="vinhos" clients={three} onChange={() => {}} />));
    await open();
    expect(container.querySelector(".clientSwitcherPanel")).toBeTruthy();
    await act(async () => {
      document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(container.querySelector(".clientSwitcherPanel")).toBeNull();
  });

  it("com 5+ empresas o foco começa na busca e ArrowDown leva à lista", async () => {
    const five = [...three, { client_id: "ruah", name: "Ruah Parfums", role: "agency_admin" }, { client_id: "latina", name: "Latina", role: "agency_admin" }];
    await act(async () => root.render(<ClientSwitcher activeClientId="vinhos" clients={five} onChange={() => {}} />));
    await open();
    expect(document.activeElement?.classList.contains("clientSwitcherSearch")).toBe(true);
    await key("ArrowDown");
    expect(document.activeElement?.textContent).toBe("Curavino");
    await key("ArrowUp");
    expect(document.activeElement?.classList.contains("clientSwitcherSearch")).toBe(true);
  });

  it("uma empresa: só a marca (logo oficial + nome acessível), sem botão", () => {
    const markup = renderToStaticMarkup(
      <ClientSwitcher activeClientId="origami" clients={[{ client_id: "origami", name: "Origami", role: "client_admin" }]} onChange={() => {}} />
    );
    expect(markup).toContain('src="/clients/origami.png"');
    expect(markup).toContain(">Origami</span>");
    expect(markup).not.toContain("<button");
  });
});
