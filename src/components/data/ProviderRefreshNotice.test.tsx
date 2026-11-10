// @vitest-environment jsdom
import {act} from "react";
import {createRoot} from "react-dom/client";
import {expect,it} from "vitest";
import {DataHealthContext} from "../../app/DataHealthContext";
import type {DataHealthSource} from "../../app/dataHealth";
import {ProviderRefreshNotice} from "./DataFreshness";
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
it("parcial vem de evidência persistida da plataforma; não transforma execução em sucesso",async()=>{
 const node=document.createElement("div"),root=createRoot(node);document.body.append(node);
 const source:DataHealthSource={provider:"meta_ads",dataset:"ads",connected:true,last_attempt_at:null,last_successful_sync_at:null,last_data_at:null,last_data_semantics:"fixture",coverage_end:null,sync_status:"partial",error_code:null,state:"attention",expected_interval_seconds:null,stale_after_seconds:null,schedule_verified:false,requested_start:"2026-10-01",requested_end:"2026-10-20"};
 const context={data:{client_id:"fixture",period:{start:"2026-10-01",end:"2026-10-20"},sources:[source]},loading:false,error:false,reload:async()=>{}};
 try {
 await act(async()=>root.render(<DataHealthContext.Provider value={context}><ProviderRefreshNotice provider="meta" control={{phase:"ready",message:""}}/></DataHealthContext.Provider>));
 expect(node.textContent).toContain("última coleta registrada");expect(node.querySelector('[data-refresh-state="partial"]')).not.toBeNull();expect(node.textContent).not.toContain("Seus dados foram atualizados");
 await act(async()=>root.render(<DataHealthContext.Provider value={context}><ProviderRefreshNotice provider="google" control={{phase:"ready",message:""}}/></DataHealthContext.Provider>));expect(node.textContent).toBe("");
 await act(async()=>root.render(<DataHealthContext.Provider value={context}><ProviderRefreshNotice provider="meta" control={{phase:"running",message:"Atualizando dados das plataformas..."}}/></DataHealthContext.Provider>));expect(node.textContent).toContain("Atualizando dados");expect(node.textContent).not.toContain("última coleta");
 }finally{await act(async()=>root.unmount());node.remove();}
});
