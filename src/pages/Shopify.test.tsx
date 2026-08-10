// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { vi, test, expect } from "vitest";
import Shopify from "./Shopify";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const refetch=vi.fn(async()=>({}));
const sync=vi.fn(async()=>({ok:true}));
vi.mock("../app/DashboardDataContext",()=>({useDashboardSnapshot:()=>({snapshot:{fetchedAt:"x"},daily:[{metric_date:"2026-08-10",shopify_net_revenue:100,shopify_gross_revenue:110,shopify_orders:2,shopify_paid_orders:2,shopify_customers:2,shopify_refunds:10}],products:[{metric_date:"2026-08-10",product_id:"p1",product_title:"Produto",variant:"",quantity:2,net_revenue:100}],sources:[{provider:"shopify",last_success_at:"2026-08-10",data_max_available:"2026-08-10"}],campaigns:[],loading:false,refreshing:false,error:null,refetch})}));
vi.mock("../app/api",()=>({resolveShopifyConnectionIdForRead:vi.fn(async()=>"conn-1"),syncShopifyConnection:(...args:unknown[])=>sync(...args)}));
vi.mock("../app/PeriodContext",()=>({usePeriod:()=>({period:{start:"2026-08-10",end:"2026-08-10"},periodDays:1,setCurrentMonthPeriod:vi.fn(),setMonthPeriod:vi.fn(),setPresetPeriod:vi.fn()})}));
vi.mock("../app/activeClient",()=>({getActiveClientId:()=>"amalie",getActiveClientName:()=>"Amalie",MUGO_APP_NAME:"Mugô Dados"}));
vi.mock("../app/syncOrchestrator",()=>({describeSyncError:()=>"erro",isSyncAlreadyRunningError:()=>false,runExclusiveSync:(_key:unknown,run:()=>Promise<unknown>)=>run()}));

test("renderiza KPIs Shopify do read model e atualização manual preserva/refaz snapshot",async()=>{const node=document.createElement("div"),root=createRoot(node);document.body.appendChild(node);await act(async()=>root.render(<Shopify onLogout={vi.fn()} onOpenDashboard={vi.fn()}/>));expect(node.textContent).toContain("110");const button=[...node.querySelectorAll("button")].find(item=>item.textContent==="Atualizar dados");await act(async()=>button?.dispatchEvent(new MouseEvent("click",{bubbles:true})));expect(sync).toHaveBeenCalledWith("conn-1",60);expect(refetch).toHaveBeenCalledTimes(1);act(()=>root.unmount());node.remove();});
