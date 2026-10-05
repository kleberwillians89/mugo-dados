// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Goal } from "../app/goals";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const state = vi.hoisted(() => ({ tenant: "a", getGoals: vi.fn(), saveGoal: vi.fn(), deleteGoal: vi.fn() }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => state.tenant, getActiveClientName: () => state.tenant }));
vi.mock("../app/PeriodContext", () => ({ usePeriod: () => ({ period: { start:"2026-09-01",end:"2026-09-30" },setPeriod:vi.fn() }) }));
vi.mock("../app/goals", async (original) => ({ ...(await original<typeof import("../app/goals")>()), getGoals:state.getGoals,saveGoal:state.saveGoal,deleteGoal:state.deleteGoal }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
import Goals from "./Goals";
import GoalsSummary from "../components/GoalsSummary";
const goal = (id="1",tenant="a"):Goal => ({ id, client_id:tenant,metric:"revenue",label:`Faturamento ${id}`,target_value:100,period_start:"2026-09-01",period_end:"2026-09-30",actual:50,available:true,origin:"Persistido",reason:null,progress_percent:50,elapsed_percent:60,pace_delta:-10,projected_value:80,remaining:50,status:"ATENCAO" });
let root:ReturnType<typeof createRoot>,node:HTMLDivElement;
beforeEach(() => { state.tenant="a"; state.getGoals.mockReset(); state.getGoals.mockResolvedValue({ client_id:"a",goals:[goal()] }); state.saveGoal.mockReset();state.saveGoal.mockResolvedValue({ok:true});state.deleteGoal.mockReset();state.deleteGoal.mockResolvedValue({ok:true});node=document.createElement("div");document.body.append(node);root=createRoot(node); });
afterEach(() => { act(() => root.unmount());node.remove(); });
const button=(label:string) => [...node.querySelectorAll("button")].find((b) => b.textContent===label)!;
async function render(admin=false) { await act(async () => root.render(<Goals canManage={admin} />)); }
test("canManage false mantém progresso sem ações de escrita",async () => { await render();expect(node.textContent).toContain("50% atingido");expect(node.textContent).toContain("Persistido");expect(node.textContent).toContain("Projeção ao fim do período");for(const name of ["+ Nova meta","Editar","Excluir"])expect(button(name)).toBeUndefined();expect(state.saveGoal).not.toHaveBeenCalled(); });
test("perfil autorizado em Metas cria, edita e exclui somente via ações explícitas",async () => {
 await render(true);expect(state.saveGoal).not.toHaveBeenCalled();
 await act(async () => button("+ Nova meta").click());
 await act(async () => { node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); });
 expect(state.saveGoal).toHaveBeenCalledWith(expect.objectContaining({metric:"revenue",period_start:"2026-09-01"}),undefined);
 await act(async () => button("Editar").click());
 await act(async () => { node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); });
 expect(state.saveGoal).toHaveBeenCalledWith(expect.objectContaining({label:"Faturamento 1"}),"1");
 await act(async () => button("Excluir").click());await act(async () => button("Excluir meta").click());expect(state.deleteGoal).toHaveBeenCalledWith("1");
});
test("dashboard mostra no máximo três metas e CTA",async () => { state.getGoals.mockResolvedValue({client_id:"a",goals:[goal("1"),goal("2"),goal("3"),goal("4")]});const open=vi.fn();await act(async () => root.render(<GoalsSummary onOpen={open} />));expect(node.querySelectorAll("article")).toHaveLength(3);expect(node.textContent).not.toContain("Faturamento 4");await act(async () => button("Ver todas as metas").click());expect(open).toHaveBeenCalledOnce(); });
test("troca de tenant oculta metas anteriores e descarta resposta atrasada",async () => {
 await render();let finish!:(value:unknown)=>void;state.tenant="b";state.getGoals.mockImplementationOnce(() => new Promise((resolve) => {finish=resolve;}));
 await act(async () => root.render(<Goals canManage={false} />));expect(node.textContent).not.toContain("Faturamento 1");
 state.tenant="c";state.getGoals.mockResolvedValue({client_id:"c",goals:[goal("C","c")]});await act(async () => root.render(<Goals canManage={false} />));
 await act(async () => finish({client_id:"b",goals:[goal("B","b")]}));expect(node.textContent).toContain("Faturamento C");expect(node.textContent).not.toContain("Faturamento B");
});
test("erro de gravação mantém metas e formulário",async () => {await render(true);state.saveGoal.mockRejectedValue(new Error("indisponível"));await act(async () => button("Editar").click());await act(async () => {node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));});expect(node.textContent).toContain("Faturamento 1");expect(node.querySelector("form")).not.toBeNull();expect(node.textContent).toContain("indisponível");});
test("dados ausentes ficam indisponíveis sem números fabricados",async () => {state.getGoals.mockResolvedValue({client_id:"a",goals:[{...goal(),actual:null,available:false,progress_percent:null,projected_value:null,status:"INDISPONIVEL",reason:"Sem snapshot"}]});await render();expect(node.textContent).toContain("Sem snapshot");expect(node.textContent).not.toContain("% atingido");});
test("formulário do tenant anterior não grava após mudança da empresa ativa",async () => {
 await render(true);await act(async () => button("+ Nova meta").click());state.tenant="b";
 await act(async () => {node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));});
 expect(state.saveGoal).not.toHaveBeenCalled();
});
