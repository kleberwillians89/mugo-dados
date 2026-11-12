// @vitest-environment jsdom
import React,{act} from "react";
import {createRoot} from "react-dom/client";
import {expect,test} from "vitest";
import PeriodTransition from "./PeriodTransition";
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
test("troca de período ou de empresa mostra esqueleto, nunca o número antigo, e troca atomicamente",async()=>{
 const node=document.createElement("div"),root=createRoot(node);
 const render=async(tenant:string,start:string,ready:boolean,text:string)=>act(async()=>root.render(<PeriodTransition tenantId={tenant} period={{start,end:"2026-10-06"}} ready={ready}><p>{text}</p></PeriodTransition>));
 await render("a","2026-10-01",true,"KPI A de outubro");
 await render("a","2026-07-09",false,"loading 90 dias");
 expect(node.querySelector("[aria-busy='true']")).not.toBeNull();expect(node.textContent).toContain("Atualizando para 2026-07-09");
 expect(node.textContent).not.toContain("KPI A de outubro");expect(node.textContent).not.toContain("loading 90 dias");
 await render("a","2026-07-09",true,"KPI A 90 dias");expect(node.textContent).toBe("KPI A 90 dias");
 await render("a","2026-07-09",false,"skeleton mesmo período");expect(node.textContent).toBe("skeleton mesmo período");
 await render("b","2026-07-09",false,"carregando B");expect(node.textContent).not.toContain("KPI A");expect(node.textContent).toContain("Carregando a leitura desta empresa");
 await render("b","2026-07-09",true,"KPI B");expect(node.textContent).toBe("KPI B");act(()=>root.unmount());
});

test("atualizações do mesmo período não congelam controles nem mensagens de erro",async()=>{
 const node=document.createElement("div"),root=createRoot(node);
 const period={start:"2026-10-01",end:"2026-10-20"};
 await act(async()=>root.render(<PeriodTransition tenantId="a" period={period} ready><button>Atualizar dados</button></PeriodTransition>));
 await act(async()=>root.render(<PeriodTransition tenantId="a" period={period} ready={false}><button disabled>Atualizando dados...</button><p role="alert">Falha de leitura</p></PeriodTransition>));
 expect(node.querySelector("button")?.disabled).toBe(true);
 expect(node.textContent).toContain("Falha de leitura");
 expect(node.textContent).not.toContain("Atualizar dados");
 act(()=>root.unmount());
});
