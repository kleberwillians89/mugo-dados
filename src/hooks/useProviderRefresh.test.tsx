// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, getProviderRefreshStatus } from "../app/api";
import { useProviderRefresh } from "./useProviderRefresh";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("../app/api", async original => ({...(await original<typeof import("../app/api")>()), getProviderRefreshStatus: vi.fn()}));
let root: Root, node: HTMLDivElement;
const task = vi.fn<() => Promise<void>>();
const ready = {client_id:"tenant-a",provider:"meta" as const,authorized:true as const,running:false,cooldown_seconds:0};
function Probe({client="tenant-a"}) {
 const refresh=useProviderRefresh(client,"meta",{start:"2026-10-01",end:"2026-10-19"},true);
 return <><span>Dados anteriores</span><button disabled={refresh.disabled} onClick={()=>void refresh.run(task).catch(()=>{})}>{refresh.label}</button><p>{refresh.error}</p><p>{refresh.message}</p></>;
}
beforeEach(()=>{vi.useFakeTimers();vi.clearAllMocks();task.mockResolvedValue();vi.mocked(getProviderRefreshStatus).mockResolvedValue(ready);node=document.createElement("div");document.body.append(node);root=createRoot(node);});
afterEach(async()=>{await act(async()=>root.unmount());node.remove();vi.useRealTimers();});
async function render(client="tenant-a"){await act(async()=>root.render(<Probe client={client}/>));}
const button=()=>node.querySelector("button")!;

it("bloqueia no mesmo clique, verifica autorização e executa uma única atualização",async()=>{
 await render();let authorize!: (value:typeof ready)=>void, finish!:()=>void;
 vi.mocked(getProviderRefreshStatus).mockImplementationOnce(()=>new Promise(resolve=>{authorize=resolve;}));
 task.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await act(async()=>{button().click();button().click();});
 expect(button().disabled).toBe(true);expect(button().textContent).toBe("Verificando acesso...");expect(task).not.toHaveBeenCalled();
 await act(async()=>authorize(ready));
 expect(button().textContent).toBe("Atualizando dados...");expect(task).toHaveBeenCalledTimes(1);
 await act(async()=>button().click());expect(task).toHaveBeenCalledTimes(1);
 await act(async()=>finish());expect(button().disabled).toBe(false);
});

it("recupera execução após remontar e só libera após backend sem execução nem cooldown",async()=>{
 vi.mocked(getProviderRefreshStatus).mockResolvedValue({...ready,running:true});await render();
 expect(button().disabled).toBe(true);expect(button().textContent).toBe("Atualizando dados...");
 await act(async()=>root.render(null));await render();expect(button().disabled).toBe(true);
 vi.mocked(getProviderRefreshStatus).mockResolvedValue({...ready,cooldown_seconds:30});
 await act(async()=>vi.advanceTimersByTimeAsync(5_000));expect(button().disabled).toBe(true);
 vi.mocked(getProviderRefreshStatus).mockResolvedValue(ready);
 await act(async()=>vi.advanceTimersByTimeAsync(5_000));expect(button().disabled).toBe(false);expect(task).not.toHaveBeenCalled();
});

it("erro HTTP não libera enquanto o backend continuar em segundo plano",async()=>{
 await render();task.mockRejectedValueOnce(new Error("network"));
 vi.mocked(getProviderRefreshStatus).mockResolvedValueOnce(ready).mockResolvedValue({...ready,running:true});
 await act(async()=>button().click());expect(button().disabled).toBe(true);expect(button().textContent).toBe("Atualizando dados...");expect(node.textContent).toContain("Dados anteriores");
 expect(task).toHaveBeenCalledTimes(1);
});

it("viewer recusado na autorização não inicia tarefa e falha de leitura não certifica liberação",async()=>{
 await render();vi.mocked(getProviderRefreshStatus).mockRejectedValue(new ApiError("denied",{status:403}));
 await act(async()=>button().click());expect(task).not.toHaveBeenCalled();expect(button().disabled).toBe(true);expect(node.textContent).toContain("não tem permissão");
});

it("status indisponível mantém bloqueio e mensagem amigável sem repetir sync",async()=>{
 vi.mocked(getProviderRefreshStatus).mockRejectedValue(new Error("offline"));await render();
 expect(button().disabled).toBe(true);expect(node.textContent).toContain("dados anteriores continuam disponíveis");expect(task).not.toHaveBeenCalled();
});

it("resposta de outro tenant não libera botão nem inicia atualização",async()=>{
 await render();vi.mocked(getProviderRefreshStatus).mockResolvedValue(ready);await render("tenant-b");
 expect(button().disabled).toBe(true);expect(task).not.toHaveBeenCalled();
});

it("negativa de autorização não repete GET no finally: dois GETs totais e nenhum POST",async()=>{
 await render();vi.mocked(getProviderRefreshStatus).mockRejectedValue(new ApiError("denied",{status:403}));
 await act(async()=>button().click());expect(getProviderRefreshStatus).toHaveBeenCalledTimes(2);expect(task).not.toHaveBeenCalled();
});
it("eventos de foco simultâneos compartilham uma única leitura em voo",async()=>{
 await render();vi.mocked(getProviderRefreshStatus).mockClear();let release!:(value:typeof ready)=>void;
 vi.mocked(getProviderRefreshStatus).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
 await act(async()=>{window.dispatchEvent(new Event("focus"));window.dispatchEvent(new Event("focus"));window.dispatchEvent(new Event("focus"));});
 expect(getProviderRefreshStatus).toHaveBeenCalledTimes(1);await act(async()=>release(ready));
});
it("duas montagens recuperam a mesma execução pelo servidor sem criar outro job",async()=>{
 let running=false,finish!:()=>void;
 vi.mocked(getProviderRefreshStatus).mockImplementation(async()=>({...ready,running}));
 task.mockImplementationOnce(()=>{running=true;return new Promise<void>(resolve=>{finish=()=>{running=false;resolve();};});});
 await act(async()=>root.render(<><Probe/><Probe/></>));const buttons=[...node.querySelectorAll("button")];
 await act(async()=>buttons[0].click());await act(async()=>window.dispatchEvent(new Event("focus")));
 expect(buttons[1].disabled).toBe(true);await act(async()=>buttons[1].click());expect(task).toHaveBeenCalledTimes(1);
 await act(async()=>finish());await act(async()=>vi.advanceTimersByTimeAsync(5000));expect(buttons[1].disabled).toBe(false);
});
it("cooldown tem mensagem explícita e sucesso depende da tarefa concluída",async()=>{
 await render();vi.mocked(getProviderRefreshStatus).mockResolvedValueOnce(ready).mockResolvedValue({...ready,cooldown_seconds:60});
 await act(async()=>button().click());expect(node.textContent).toContain("Seus dados foram atualizados.");expect(node.textContent).toContain("Você poderá atualizar novamente");expect(button().disabled).toBe(true);
});


it("não continua consultando o Supabase quando o refresh já está pronto", async () => {
 await render();
 vi.mocked(getProviderRefreshStatus).mockClear();
 await act(async()=>vi.advanceTimersByTimeAsync(120_000));
 expect(getProviderRefreshStatus).not.toHaveBeenCalled();
 await act(async()=>window.dispatchEvent(new Event("focus")));
 expect(getProviderRefreshStatus).toHaveBeenCalledTimes(1);
});

it("reduz polling durante cooldown longo sem liberar atualização antecipadamente", async () => {
 vi.mocked(getProviderRefreshStatus).mockResolvedValue({...ready,cooldown_seconds:60});
 await render();
 vi.mocked(getProviderRefreshStatus).mockClear();
 await act(async()=>vi.advanceTimersByTimeAsync(5_000));
 expect(getProviderRefreshStatus).not.toHaveBeenCalled();
 await act(async()=>vi.advanceTimersByTimeAsync(10_000));
 expect(getProviderRefreshStatus).toHaveBeenCalledTimes(1);
 expect(button().disabled).toBe(true);
});
