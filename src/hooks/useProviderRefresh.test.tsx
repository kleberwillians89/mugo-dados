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
 return <><span>Dados anteriores</span><button disabled={refresh.disabled} onClick={()=>void refresh.run(task).catch(()=>{})}>{refresh.label}</button><p>{refresh.error}</p></>;
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
