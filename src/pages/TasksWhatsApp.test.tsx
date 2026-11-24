// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../components/data/PageHeader", () => ({ default: ({ title, controls }: { title: string; controls?: React.ReactNode }) => <header><h1>{title}</h1>{controls}</header> }));
vi.mock("../components/studio/TaskBoard", () => ({ default: () => <div>quadro</div> }));
vi.mock("../components/studio/ClientTasks", () => ({ default: () => null }));
vi.mock("../app/studio", () => ({ getCentral: vi.fn(() => new Promise(() => undefined)) }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "ruah", getActiveClientName: () => "Ruah" }));

import Tasks from "./Tasks";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement; let root: ReturnType<typeof createRoot>;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === label);

describe("Meu trabalho: acesso operacional ao WhatsApp", () => {
  it("mostra 'Atendimento WhatsApp' ao lado das tarefas e abre a ferramenta", async () => {
    const open = vi.fn();
    await act(async () => root.render(<Tasks onOpenWhatsApp={open} />));
    expect(host.textContent).toContain("quadro");  // as tarefas continuam iguais
    expect(host.querySelector(".ds-page.mugoBrand")).not.toBeNull();  // identidade Mugô aplicada na tela
    await act(async () => btn("Atendimento WhatsApp")!.click());
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("sem permissão de WhatsApp, o botão não aparece", async () => {
    await act(async () => root.render(<Tasks />));
    expect(btn("Atendimento WhatsApp")).toBeUndefined();
    expect(btn("Atualizar")).toBeTruthy();
  });
});
