// @vitest-environment jsdom
import React,{act} from "react";
import {createRoot} from "react-dom/client";
import {expect,test,vi} from "vitest";
import {listGenericConnections,getGa4Report} from "../../app/api";
import useGa4Readiness from "./useGa4Readiness";
import useDashboardGa4 from "./useDashboardGa4";
vi.mock("../../app/api",()=>({listGenericConnections:vi.fn(),getGa4Report:vi.fn(async()=>({client_id:"configured",summary:{sessions:5},meta:{last_synced_at:null}}))}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
test("readiness persistida bloqueia report, permite configuração válida e não repete configuração por período",async()=>{
 vi.mocked(listGenericConnections).mockImplementation(async()=>({ok:true,client_id:"readiness-fixture",connections:[{id:"ga4",client_id:"readiness-fixture",provider:"ga4",status:"connected",capabilities:{ga4_configured:false,ga4_authorized:true,ga4_status:"needs_configuration",ads_authorized:false,ads_configured:false,ads_status:"not_configured"}}]}));
 const node=document.createElement("div"),root=createRoot(node);
 function Page({days,clientId="readiness-fixture"}:{days:number;clientId?:string}){const readiness=useGa4Readiness(clientId,true);useDashboardGa4({isAuthenticated:true,activeClientId:clientId,enabled:readiness.ready===true,period:{start:days===7?"2026-10-01":"2026-09-07",end:"2026-10-07"}});return <span>{String(readiness.ready)}</span>;}
 await act(async()=>root.render(<React.StrictMode><Page days={7}/></React.StrictMode>));
 await act(async()=>new Promise(resolve=>setTimeout(resolve,5)));
 expect(node.textContent).toBe("false");expect(getGa4Report).not.toHaveBeenCalled();expect(listGenericConnections).toHaveBeenCalledTimes(1);
 await act(async()=>root.render(<React.StrictMode><Page days={30}/></React.StrictMode>));
 expect(listGenericConnections).toHaveBeenCalledTimes(1);expect(getGa4Report).not.toHaveBeenCalled();
 vi.mocked(listGenericConnections).mockResolvedValue({ok:true,client_id:"configured",connections:[{id:"configured-ga4",client_id:"configured",provider:"ga4",status:"connected",capabilities:{ga4_configured:true,ga4_authorized:true,ga4_status:"configured",ads_authorized:false,ads_configured:false,ads_status:"not_configured"}}]});
 await act(async()=>root.render(<React.StrictMode><Page days={30} clientId="configured"/></React.StrictMode>));
 await act(async()=>new Promise(resolve=>setTimeout(resolve,5)));
 expect(node.textContent).toBe("true");expect(getGa4Report).toHaveBeenCalledTimes(1);
 expect(vi.mocked(getGa4Report).mock.calls[0][1]?.clientId).toBe("configured");
 let finish!: (value: Awaited<ReturnType<typeof listGenericConnections>>) => void;
 vi.mocked(listGenericConnections).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await act(async()=>root.render(<React.StrictMode><Page days={30} clientId="unresolved-b"/></React.StrictMode>));
 expect(node.textContent).toBe("null");expect(getGa4Report).toHaveBeenCalledTimes(1);
 await act(async()=>finish({ok:true,client_id:"unresolved-b",connections:[]}));
 expect(node.textContent).toBe("false");expect(getGa4Report).toHaveBeenCalledTimes(1);
 act(()=>root.unmount());
});
