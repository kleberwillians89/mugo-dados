// @vitest-environment jsdom
import React,{act} from "react";
import {createRoot} from "react-dom/client";
import {expect,test} from "vitest";
import PeriodTransition from "./PeriodTransition";
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
test("retém composição do período anterior com aviso explícito, troca atomicamente e não retém outro tenant",async()=>{
 const node=document.createElement("div"),root=createRoot(node);
 let mounts=0;
 function Content({text}:{text:string}){React.useEffect(()=>{mounts++;},[]);return <p>{text}</p>;}
 const render=async(tenant:string,start:string,ready:boolean,text:string)=>act(async()=>root.render(<PeriodTransition tenantId={tenant} period={{start,end:"2026-10-06"}} ready={ready}><Content text={text}/></PeriodTransition>));
 await render("a","2026-10-01",true,"KPI A de outubro");
 await render("a","2026-07-09",false,"loading 90 dias");
 expect(node.textContent).toContain("Atualizando período...");expect(node.textContent).toContain("2026-10-01");expect(node.textContent).toContain("KPI A de outubro");expect(node.textContent).not.toContain("loading 90 dias");
 expect(mounts).toBe(1);
 await render("a","2026-07-09",true,"KPI A 90 dias");expect(node.textContent).toBe("KPI A 90 dias");
 await render("a","2026-07-09",false,"skeleton mesmo período");expect(node.textContent).toContain("Atualizando leitura...");expect(node.textContent).toContain("KPI A 90 dias");expect(mounts).toBe(1);
 await render("b","2026-07-09",false,"carregando B");expect(node.textContent).not.toContain("KPI A");
 await render("b","2026-07-09",true,"KPI B");expect(node.textContent).toBe("KPI B");act(()=>root.unmount());
});
