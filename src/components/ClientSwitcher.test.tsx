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

  it("renders the selected company with an accessible tenant selector", () => {
    const markup = renderToStaticMarkup(
      <ClientSwitcher
        activeClientId="roove"
        clients={[{ client_id: "roove", name: "Roove", role: "platform_admin" }]}
        onChange={() => {}}
      />
    );
    expect(markup).toContain('aria-label="Selecionar empresa"');
    expect(markup).toContain("Roove");
    expect(markup).toContain("Empresa ativa");
  });

  it("keeps the selector in document flow and gives mobile layout its own row", () => {
    const cssPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../styles/App.css");
    const css = readFileSync(cssPath, "utf8");
    expect(css).toMatch(/\.clientSwitcher\{[\s\S]*?position:static/);
    expect(css).toMatch(/@media\(max-width:980px\)[\s\S]*?\.clientSwitcher\{width:100%/);
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
