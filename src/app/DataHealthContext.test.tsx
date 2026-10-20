// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { DataHealthProvider, DataHealthContext } from "./DataHealthContext";
import { DataFreshness, DataHealthSummary } from "../components/data/DataFreshness";
import { DATA_HEALTH_CHANGED, type DataHealthResponse, type DataHealthSource } from "./dataHealth";
import { getClientDataHealth } from "./api";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const state = vi.hoisted(() => ({period: {start: "2026-10-01", end: "2026-10-19"}}));
vi.mock("./api", () => ({getClientDataHealth: vi.fn()}));
vi.mock("./PeriodContext", () => ({useOptionalPeriod: () => ({period: state.period})}));
const stamp = "2026-10-19T12:00:00Z";
const source: DataHealthSource = {provider:"ga4", dataset:"ga4", connected:true, last_attempt_at:stamp,
 last_successful_sync_at:stamp, last_data_at:"2026-10-17", last_data_semantics:"metric_day", coverage_end:null,
 sync_status:"partial", error_code:"INCOMPLETE_COLLECTION", state:"attention", expected_interval_seconds:10800,
 stale_after_seconds:21600, schedule_verified:false, requested_start:"2026-10-01", requested_end:"2026-10-19"};
function response(client="tenant-a", sources=[source]): DataHealthResponse {return {client_id:client, period:{...state.period}, sources};}
let host: HTMLDivElement, root: Root;
beforeEach(() => {vi.clearAllMocks();state.period={start:"2026-10-01",end:"2026-10-19"};host=document.createElement("div");document.body.append(host);root=createRoot(host);vi.mocked(getClientDataHealth).mockResolvedValue(response());});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function render(client="tenant-a") {await act(async()=>root.render(<DataHealthProvider clientId={client} enabled><DataFreshness provider="ga4" /><DataHealthSummary /></DataHealthProvider>));}

describe("saúde por fonte e período",()=>{
 it("separa última sincronização, data dos fatos e cobertura desconhecida",async()=>{
  await render();expect(host.textContent).toContain("Última sincronização");expect(host.textContent).toContain("17/10/2026");expect(host.textContent).toContain("cobertura não comprovada");expect(host.textContent).toContain("Atenção");
 });
 it("navegação e rerender não sincronizam nem repetem a leitura",async()=>{
  await render();await render();expect(getClientDataHealth).toHaveBeenCalledTimes(1);
 });
 it("troca de cliente esconde o estado anterior antes de resposta nova",async()=>{
  await render();let finish!: (data:DataHealthResponse)=>void;
  vi.mocked(getClientDataHealth).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await render("tenant-b");expect(host.textContent).not.toContain("17/10/2026");
  await act(async()=>finish(response("tenant-b",[{...source,last_data_at:"2026-10-18"}])));expect(host.textContent).toContain("18/10/2026");
 });
 it("troca de período não apresenta timestamp anterior como atual",async()=>{
  await render();state.period={start:"2026-09-01",end:"2026-09-30"};
  vi.mocked(getClientDataHealth).mockResolvedValueOnce(response("tenant-a",[{...source,last_data_at:null,last_successful_sync_at:null,coverage_end:null,state:"no_data"}]))
  await render();expect(host.textContent).not.toContain("17/10/2026");expect(host.textContent).toContain("sem sucesso confirmado");
 });
 it("ignora resposta atrasada do tenant anterior",async()=>{
  let finish!: (data:DataHealthResponse)=>void;
  vi.mocked(getClientDataHealth).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await render();vi.mocked(getClientDataHealth).mockResolvedValueOnce(response("tenant-b",[{...source,last_data_at:"2026-10-18"}]));await render("tenant-b");
  await act(async()=>finish(response("tenant-a")));expect(host.textContent).toContain("18/10/2026");expect(host.textContent).not.toContain("17/10/2026");
 });
 it("relê evidência após refresh sem inventar sucesso",async()=>{
  await render();vi.mocked(getClientDataHealth).mockResolvedValueOnce(response("tenant-a",[{...source,sync_status:"error",state:"attention"}]));
  await act(async()=>{window.dispatchEvent(new CustomEvent(DATA_HEALTH_CHANGED,{detail:{clientId:"tenant-a"}}));});
  expect(getClientDataHealth).toHaveBeenCalledTimes(2);expect(host.textContent).toContain("Atenção");expect(host.textContent).not.toContain("Sincronizado");
 });
 it("ação de reconectar só aparece com autorização explícita da aplicação",async()=>{
  const value={data:response("tenant-a",[{...source,state:"reauth_required"}]),loading:false,error:false,reload:async()=>{}};
  await act(async()=>root.render(<DataHealthContext.Provider value={value}><DataHealthSummary /></DataHealthContext.Provider>));
  expect(host.textContent).toContain("Reconexão necessária");expect([...host.querySelectorAll("button")].some(button=>button.textContent === "Reconectar")).toBe(false);
  await act(async()=>root.render(<DataHealthContext.Provider value={value}><DataHealthSummary onReconnect={()=>{}} /></DataHealthContext.Provider>));expect([...host.querySelectorAll("button")].some(button=>button.textContent === "Reconectar")).toBe(true);
 });
 it("erro de leitura preserva evidência anterior identificada",async()=>{
  await render();vi.mocked(getClientDataHealth).mockRejectedValueOnce(new Error("fixture"));
  await act(async()=>{window.dispatchEvent(new CustomEvent(DATA_HEALTH_CHANGED,{detail:{clientId:"tenant-a"}}));});
  expect(host.textContent).toContain("última evidência");expect(host.textContent).toContain("17/10/2026");
 });
});

it("indicador só avança para sincronizado após reler sucesso e cobertura persistidos", async()=>{
 await render();
 vi.mocked(getClientDataHealth).mockResolvedValueOnce(response("tenant-a",[{...source, sync_status:"success",state:"synced",error_code:null,coverage_end:"2026-10-19",last_data_at:"2026-10-19"}]));
 await act(async()=>{window.dispatchEvent(new CustomEvent(DATA_HEALTH_CHANGED,{detail:{clientId:"tenant-a"}}));});
 expect(host.textContent).toContain("Sincronizado");expect(host.textContent).toContain("Cobertura verificada até 19/10/2026");
});

it("coalesce notificações durante GET e relê uma vez após a conclusão do sync", async () => {
 let finish!: (data: DataHealthResponse) => void;
 vi.mocked(getClientDataHealth).mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}));
 await render();
 await act(async () => {
  for (let i=0; i<4; i++) window.dispatchEvent(new CustomEvent(DATA_HEALTH_CHANGED,{detail:{clientId:"tenant-a"}}));
 });
 expect(getClientDataHealth).toHaveBeenCalledTimes(1);
 vi.mocked(getClientDataHealth).mockResolvedValueOnce(response("tenant-a",[{...source,state:"synced",sync_status:"success",coverage_end:"2026-10-19"}]));
 await act(async () => finish(response()));
 expect(getClientDataHealth).toHaveBeenCalledTimes(2);
 expect(host.textContent).toContain("Sincronizado");
});

it("Roove → Ruah → Origami descarta respostas e notificações antigas", async () => {
 const finish: Array<(data:DataHealthResponse)=>void> = [];
 vi.mocked(getClientDataHealth).mockImplementation(() => new Promise(resolve => {finish.push(resolve);}));
 await render("roove"); await render("ruah"); await render("origami");
 await act(async () => {
  window.dispatchEvent(new CustomEvent(DATA_HEALTH_CHANGED,{detail:{clientId:"roove"}}));
  finish[2](response("origami",[{...source,last_data_at:"2026-10-19"}]));
  finish[0](response("roove")); finish[1](response("ruah"));
 });
 expect(getClientDataHealth).toHaveBeenCalledTimes(3);
 expect(host.textContent).toContain("19/10/2026");
 expect(host.textContent).not.toContain("17/10/2026");
});

it("desabilitar e reabilitar não reutiliza GET invalidado nem prende loading", async () => {
 let finish!: (data:DataHealthResponse)=>void;
 vi.mocked(getClientDataHealth).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await render();
 await act(async()=>root.render(<DataHealthProvider clientId="tenant-a" enabled={false}><DataFreshness provider="ga4" /></DataHealthProvider>));
 vi.mocked(getClientDataHealth).mockResolvedValueOnce(response());
 await render();
 await act(async()=>finish(response("tenant-a",[{...source,last_data_at:"2026-10-16"}])));
 expect(getClientDataHealth).toHaveBeenCalledTimes(2);
 expect(host.textContent).toContain("17/10/2026");
 expect(host.textContent).not.toContain("16/10/2026");
});
