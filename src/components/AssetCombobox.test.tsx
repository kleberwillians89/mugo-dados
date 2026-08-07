// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AssetCombobox, { type AssetComboboxOption } from "./AssetCombobox";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const OPTIONS: AssetComboboxOption[] = [
  { value: "act_1", label: "RŪAH", subtitle: "Conta de anúncios", meta: "139-186-3696" },
  { value: "act_2", label: "Amalie", subtitle: "Conta de anúncios", meta: "123-456-7890" },
];

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

function getInput(): HTMLInputElement {
  return container.querySelector("input") as HTMLInputElement;
}

function setInputValue(value: string) {
  const input = getInput();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("AssetCombobox", () => {
  it("nunca mostra apenas o ID cru — mostra nome forte, subtítulo e ID menor por opção", async () => {
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={() => {}} options={OPTIONS} />);
    });
    await act(async () => {
      getInput().focus();
    });
    const optionText = container.querySelector(".assetComboboxOption")?.textContent || "";
    expect(optionText).toContain("RŪAH");
    expect(optionText).toContain("Conta de anúncios");
    expect(optionText).toContain("139-186-3696");
  });

  it("filtra opções pela busca (nome, subtítulo ou ID)", async () => {
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={() => {}} options={OPTIONS} />);
    });
    await act(async () => {
      getInput().focus();
    });
    await act(async () => {
      setInputValue("Amalie");
    });
    const items = [...container.querySelectorAll(".assetComboboxOption")];
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain("Amalie");
  });

  it("seleciona com teclado: ArrowDown + Enter", async () => {
    const onChange = vi.fn();
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={onChange} options={OPTIONS} />);
    });
    await act(async () => {
      getInput().focus();
    });
    await act(async () => {
      getInput().dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    await act(async () => {
      getInput().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith("act_2");
  });

  it("Escape fecha a lista sem selecionar", async () => {
    const onChange = vi.fn();
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={onChange} options={OPTIONS} />);
    });
    await act(async () => {
      getInput().focus();
    });
    expect(container.querySelector(".assetComboboxList")).toBeTruthy();
    await act(async () => {
      getInput().dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector(".assetComboboxList")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("mostra estado vazio quando a busca não encontra nada", async () => {
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={() => {}} options={OPTIONS} emptyMessage="Nada encontrado." />);
    });
    await act(async () => {
      getInput().focus();
    });
    await act(async () => {
      setInputValue("zzz-inexistente");
    });
    expect(container.textContent).toContain("Nada encontrado.");
  });

  it("mostra estado de carregamento", async () => {
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={() => {}} options={[]} loading />);
    });
    expect(container.querySelector(".assetComboboxSpinner")).toBeTruthy();
    await act(async () => {
      getInput().focus();
    });
    expect(container.textContent).toContain("Carregando...");
  });

  it("respeita disabled — não abre a lista", async () => {
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={() => {}} options={OPTIONS} disabled />);
    });
    expect(getInput().disabled).toBe(true);
    await act(async () => {
      getInput().focus();
    });
    expect(container.querySelector(".assetComboboxList")).toBeNull();
  });

  it("mostra mensagem de erro quando fornecida", async () => {
    await act(async () => {
      root.render(<AssetCombobox label="Conta" value="" onChange={() => {}} options={OPTIONS} error="Não foi possível carregar as contas." />);
    });
    expect(container.textContent).toContain("Não foi possível carregar as contas.");
  });
});
