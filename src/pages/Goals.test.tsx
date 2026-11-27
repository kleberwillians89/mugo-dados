// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Goal } from "../app/goals";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const state = vi.hoisted(() => ({ tenant: "a", getGoals: vi.fn(), saveGoal: vi.fn(), deleteGoal: vi.fn(), suggestGoal: vi.fn(), getGoalDrivers: vi.fn(), getGoalHistory: vi.fn() }));
vi.mock("../app/crm", async (original) => ({ ...(await original<typeof import("../app/crm")>()), listAssignees: async () => ({ available: true, people: [{ user_id: "u2", name: "Julia" }] }) }));
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => state.tenant, getActiveClientName: () => state.tenant }));
vi.mock("../app/PeriodContext", () => ({ usePeriod: () => ({ period: { start:"2026-09-01",end:"2026-09-30" },setPeriod:vi.fn() }) }));
vi.mock("../app/goals", async (original) => ({ ...(await original<typeof import("../app/goals")>()), getGoals:state.getGoals,saveGoal:state.saveGoal,deleteGoal:state.deleteGoal,suggestGoal:state.suggestGoal,getGoalDrivers:state.getGoalDrivers,getGoalHistory:state.getGoalHistory }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
import Goals from "./Goals";
import GoalsSummary from "../components/GoalsSummary";
const goal = (id="1",tenant="a"):Goal => ({ id, client_id:tenant,metric:"revenue",label:`Faturamento ${id}`,target_value:100,period_start:"2026-09-01",period_end:"2026-09-30",actual:50,available:true,origin:"Persistido",reason:null,progress_percent:50,elapsed_percent:60,pace_delta:-10,projected_value:80,remaining:50,status:"ATENCAO",direction:"min",additive:true,days_left:11,required_daily:50/11,observed_daily:2.5,covered_days:20,pace_model:"linear" });
let root:ReturnType<typeof createRoot>,node:HTMLDivElement;
beforeEach(() => { state.tenant="a"; state.getGoals.mockReset(); state.getGoals.mockResolvedValue({ client_id:"a",goals:[goal()] }); state.saveGoal.mockReset();state.saveGoal.mockResolvedValue({ok:true});state.deleteGoal.mockReset();state.deleteGoal.mockResolvedValue({ok:true});node=document.createElement("div");document.body.append(node);root=createRoot(node); });
afterEach(() => { act(() => root.unmount());node.remove(); });
const button=(label:string) => [...node.querySelectorAll("button")].find((b) => b.textContent===label)!;
async function render(admin=false) { await act(async () => root.render(<Goals canManage={admin} />)); }
test("canManage false mantém progresso sem ações de escrita",async () => { await render();expect(node.textContent).toContain("Minha meta");expect(node.textContent).toContain("Já alcançamos");expect(node.textContent).toContain("Persistido");expect(node.textContent).toContain("Projeção ao fim");for(const name of ["+ Nova meta","Editar minha meta","Excluir minha meta"])expect(button(name)).toBeUndefined();expect(state.saveGoal).not.toHaveBeenCalled(); });
test("perfil autorizado em Metas cria, edita e exclui somente via ações explícitas",async () => {
 await render(true);expect(state.saveGoal).not.toHaveBeenCalled();
 await act(async () => button("+ Nova meta").click());
 const target=[...node.querySelectorAll<HTMLInputElement>("form input[type=number]")][0];
 expect(target.value).toBe("");  // sem valor fictício pré-preenchido
 await act(async () => { node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); });
 expect(state.saveGoal).not.toHaveBeenCalled();  // sem alvo, não grava
 await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(target,"80000"); target.dispatchEvent(new Event("input",{bubbles:true})); });
 await act(async () => { node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); });
 expect(state.saveGoal).toHaveBeenCalledWith(expect.objectContaining({metric:"revenue",period_start:"2026-09-01",target_value:80000}),undefined);
 await act(async () => button("Editar minha meta").click());
 await act(async () => { node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); });
 expect(state.saveGoal).toHaveBeenCalledWith(expect.objectContaining({label:"Faturamento 1"}),"1");
 await act(async () => button("Excluir minha meta").click());await act(async () => button("Excluir meta").click());expect(state.deleteGoal).toHaveBeenCalledWith("1");
});
test("dashboard mostra no máximo três metas e CTA",async () => { state.getGoals.mockResolvedValue({client_id:"a",goals:[goal("1"),goal("2"),goal("3"),goal("4")]});const open=vi.fn();await act(async () => root.render(<GoalsSummary onOpen={open} />));expect(node.querySelectorAll("article")).toHaveLength(3);expect(node.textContent).not.toContain("Faturamento 4");await act(async () => button("Ver todas as metas").click());expect(open).toHaveBeenCalledOnce(); });
test("troca de tenant oculta metas anteriores e descarta resposta atrasada",async () => {
 await render();let finish!:(value:unknown)=>void;state.tenant="b";state.getGoals.mockImplementationOnce(() => new Promise((resolve) => {finish=resolve;}));
 await act(async () => root.render(<Goals canManage={false} />));expect(node.textContent).not.toContain("Faturamento 1");
 state.tenant="c";state.getGoals.mockResolvedValue({client_id:"c",goals:[goal("C","c")]});await act(async () => root.render(<Goals canManage={false} />));
 await act(async () => finish({client_id:"b",goals:[goal("B","b")]}));expect(node.textContent).toContain("Faturamento C");expect(node.textContent).not.toContain("Faturamento B");
});
test("erro de gravação mantém metas e formulário",async () => {await render(true);state.saveGoal.mockRejectedValue(new Error("indisponível"));await act(async () => button("Editar minha meta").click());await act(async () => {node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));});expect(node.textContent).toContain("Faturamento 1");expect(node.querySelector("form")).not.toBeNull();expect(node.textContent).toContain("indisponível");});
test("dados ausentes ficam indisponíveis sem números fabricados",async () => {state.getGoals.mockResolvedValue({client_id:"a",goals:[{...goal(),actual:null,available:false,progress_percent:null,projected_value:null,status:"INDISPONIVEL",reason:"Sem snapshot"}]});await render();expect(node.textContent).toContain("Sem snapshot");expect(node.textContent).not.toContain("% atingido");});
test("formulário do tenant anterior não grava após mudança da empresa ativa",async () => {
 await render(true);await act(async () => button("+ Nova meta").click());state.tenant="b";
 await act(async () => {node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));});
 expect(state.saveGoal).not.toHaveBeenCalled();
});

test("minha meta mostra quanto falta e o necessário por dia; ritmo abaixo é explicado",async () => {
 state.getGoals.mockResolvedValue({client_id:"a",goals:[{...goal(),target_value:100000,actual:34000,remaining:66000,days_left:6,required_daily:11000,observed_daily:1416.67,pace_note:"O ritmo observado está 87% abaixo do necessário por dia."}]});
 await render();
 expect(node.textContent).toMatch(/Faltam R\$\s*66\.000,00\. Com 6 dias restantes, é preciso R\$\s*11\.000,00 por dia\./);
 expect(node.textContent).toContain("87% abaixo do necessário");
 expect(node.textContent).toContain("ritmo linear");
});
test("meta máxima fala em teto, não em falta",async () => {
 state.getGoals.mockResolvedValue({client_id:"a",goals:[{...goal(),metric:"ad_spend",label:"Investimento",direction:"max",status:"DENTRO_DO_TETO",target_value:3000,actual:800,remaining:2200,days_left:21,required_daily:2200/21}]});
 await render();
 expect(node.textContent).toContain("Não passar de");
 expect(node.textContent).toContain("Folga até o teto");
 expect(node.textContent).toContain("Dentro do teto");
});
test("sugerir meta mostra cenários com premissas e só preenche quando a pessoa escolhe",async () => {
 state.suggestGoal.mockResolvedValue({available:true,uncertainty:"média",scenarios:[{key:"conservador",label:"Conservador",value:80000},{key:"referencia",label:"Referência",value:90000},{key:"agressivo",label:"Agressivo",value:110000}],
   premises:{model:"Períodos anteriores do mesmo tamanho; ritmo linear.",commercial_dates:["Black Friday"],seasonality_note:"O período inclui Black Friday.",history:[{start:"2026-06-03",end:"2026-07-02",value:80000,coverage:1,origin:null,reason:null}]}});
 await render(true);
 await act(async () => button("+ Nova meta").click());
 await act(async () => button("Sugerir meta").click());
 expect(node.textContent).toContain("O período inclui Black Friday.");
 const target=[...node.querySelectorAll<HTMLInputElement>("form input[type=number]")][0];
 expect(target.value).toBe("");
 await act(async () => [...node.querySelectorAll<HTMLButtonElement>(".goalScenarioPick button")][1].click());
 expect(target.value).toBe("90000");
 await act(async () => { node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); });
 expect(state.saveGoal).toHaveBeenCalledWith(expect.objectContaining({target_value:90000,suggestion:expect.objectContaining({key:"referencia"})}),undefined);
});
test("indicador relacionado vira submeta só com confirmação",async () => {
 state.getGoalDrivers.mockResolvedValue({relation:"Faturamento = Pedidos × Ticket médio",note:"Referência.",drivers:[{metric:"orders",label:"Pedidos",available:true,actual:400,origin:"Shopify",reason:null,needed:500,direction:"min"},
   {metric:"average_ticket",label:"Ticket médio",available:false,actual:null,origin:null,reason:"Não há pedidos",needed:null,direction:"min"}]});
 await render(true);
 await act(async () => button("Explorar indicadores e cenários").click());
 await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
 expect(node.textContent).toContain("Faturamento = Pedidos × Ticket médio");
 expect(node.textContent).toContain("Dados indisponíveis");
 expect(state.saveGoal).not.toHaveBeenCalled();
 await act(async () => button("Transformar em submeta").click());
 const target=[...node.querySelectorAll<HTMLInputElement>("form input[type=number]")][0];
 expect(target.value).toBe("500");
 await act(async () => { node.querySelector("form")!.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); });
 expect(state.saveGoal).toHaveBeenCalledWith(expect.objectContaining({metric:"orders",parent_goal_id:"1",relation:"Faturamento = Pedidos × Ticket médio",is_primary:false}),undefined);
});
test("ritmo sazonal aparece só quando calculado e diz o necessário hoje",async () => {
 state.getGoals.mockResolvedValue({client_id:"a",goals:[{...goal(),pace_model:"sazonal",required_today:140,curve:[1,1,1,1,1,2,2]}]});
 await render();
 expect(node.textContent).toContain("Necessário hoje (dias da semana)");
 expect(node.textContent).toContain("ritmo pelos dias da semana da marca");
});
