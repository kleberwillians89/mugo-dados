// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({ getMugoIA: vi.fn(), askMugoIA: vi.fn(), clearMugoIA: vi.fn(), addKnowledgeFacts: vi.fn() }));
vi.mock("../app/studio", async (original) => ({ ...(await original<typeof import("../app/studio")>()), ...studio }));
vi.mock("../app/activeClient", async (original) => ({ ...(await original<typeof import("../app/activeClient")>()), getActiveClientName: () => "Ruah" }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: unknown }) => <div>{children as never}</div> }));

import MugoIA from "./MugoIA";

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const btn = (label: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement;

describe("Mugoverso IA", () => {
  it("responde com fontes, lacunas e próximas perguntas", async () => {
    studio.getMugoIA.mockResolvedValue({ messages: [] });
    studio.askMugoIA.mockResolvedValue({ ok: true, id: "m1", answer: "Índice 71: saudável.", on_topic: true, sources: ["Saúde da marca", "Concorrentes"],
      new_facts: ["Não fazemos desconto em dezembro"], follow_ups: ["E os concorrentes?"], coverage: { read: ["Saúde da marca"], gaps: ["sem_metas_no_mes"] } });
    studio.addKnowledgeFacts.mockResolvedValue({});
    await act(async () => { root.render(<MugoIA canManage isAgency />); });
    expect(host.textContent).toContain("Quais alertas e tarefas abertas pedem atenção?");  // sugestão da equipe
    await act(async () => { btn("Como está a saúde da marca e o que o público anda falando?").click(); });
    expect(studio.askMugoIA).toHaveBeenCalledWith("Como está a saúde da marca e o que o público anda falando?");
    expect(host.textContent).toContain("Índice 71: saudável.");
    expect(host.querySelector(".miaChips")?.textContent).toBe("Com base emSaúde da marcaConcorrentes");
    expect(host.querySelector(".miaChips.is-gap")?.textContent).toBe("Sem dado agorametas do mês");
    await act(async () => { btn("Guardar na memória da marca").click(); });
    expect(studio.addKnowledgeFacts).toHaveBeenCalledWith(["Não fazemos desconto em dezembro"]);
    studio.askMugoIA.mockResolvedValue({ ok: true, id: "m2", answer: "A Marca X lançou um perfume.", on_topic: true, sources: [], new_facts: [], follow_ups: [], coverage: { read: [], gaps: [] } });
    await act(async () => { btn("E os concorrentes?").click(); });
    expect(studio.askMugoIA).toHaveBeenLastCalledWith("E os concorrentes?");
    expect(host.textContent).toContain("A Marca X lançou um perfume.");
  });

  it("cliente vê sugestões dele e não guarda fatos", async () => {
    studio.getMugoIA.mockResolvedValue({ messages: [{ id: "a", role: "assistant", content: "Oi", meta: { new_facts: ["x"] } }] });
    await act(async () => { root.render(<MugoIA canManage={false} isAgency={false} />); });
    expect(host.textContent).not.toContain("Guardar na memória da marca");
    await act(async () => { btn("Nova conversa").click(); });
    studio.clearMugoIA.mockResolvedValue({ ok: true });
    await act(async () => { btn("Apagar").click(); });
    expect(studio.clearMugoIA).toHaveBeenCalled();
    expect(host.textContent).toContain("Como está a saúde da minha marca?");
  });

  it("formata a resposta: parágrafos, lista e o bloco do que fazer agora", async () => {
    studio.getMugoIA.mockResolvedValue({ messages: [{ id: "a", role: "assistant", content:
      "Kleber, a marca está muito bem vista.\n\n- 36 menções, 97% positivas\n- elogios ao conteúdo\n\nO que eu faria agora: aproveitar a Black November." }] });
    await act(async () => { root.render(<MugoIA canManage isAgency />); });
    expect(host.querySelector(".miaAnswer p")?.textContent).toBe("Kleber, a marca está muito bem vista.");
    expect(host.querySelectorAll(".miaAnswer > ul li")).toHaveLength(2);
    expect(host.querySelector(".miaAction")?.textContent).toBe("O que eu faria agoraaproveitar a Black November.");
  });

  it("erro devolve a pergunta para a caixa", async () => {
    studio.getMugoIA.mockResolvedValue({ messages: [] });
    studio.askMugoIA.mockRejectedValue(new Error("Muitas perguntas agora."));
    await act(async () => { root.render(<MugoIA canManage isAgency />); });
    await act(async () => { btn("O que os concorrentes fizeram nas últimas semanas?").click(); });
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("Muitas perguntas agora.");
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe("O que os concorrentes fizeram nas últimas semanas?");
  });
});
