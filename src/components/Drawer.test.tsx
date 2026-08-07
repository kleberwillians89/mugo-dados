// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Drawer from "./Drawer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

describe("Drawer", () => {
  it("não renderiza nada quando fechado", async () => {
    await act(async () => {
      root.render(<Drawer open={false} title="Editar" onClose={() => {}}>conteúdo</Drawer>);
    });
    expect(container.querySelector(".drawerBackdrop")).toBeNull();
  });

  it("chama onClose ao pressionar Esc", async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(<Drawer open title="Editar" onClose={onClose}>conteúdo</Drawer>);
    });
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("chama onClose ao clicar no backdrop, mas não ao clicar dentro do painel", async () => {
    const onClose = vi.fn();
    await act(async () => {
      root.render(<Drawer open title="Editar" onClose={onClose}>conteúdo</Drawer>);
    });
    const panel = container.querySelector(".drawerPanel") as HTMLElement;
    await act(async () => {
      panel.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(onClose).not.toHaveBeenCalled();

    const backdrop = container.querySelector(".drawerBackdrop") as HTMLElement;
    await act(async () => {
      backdrop.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renderiza título, descrição, conteúdo e rodapé", async () => {
    await act(async () => {
      root.render(
        <Drawer open title="Editar empresa" description="Geral" onClose={() => {}} footer={<button>Salvar</button>}>
          <p>corpo</p>
        </Drawer>
      );
    });
    expect(container.textContent).toContain("Editar empresa");
    expect(container.textContent).toContain("Geral");
    expect(container.textContent).toContain("corpo");
    expect(container.textContent).toContain("Salvar");
  });
});
