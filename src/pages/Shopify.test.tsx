// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { vi, test, expect } from "vitest";
import Shopify from "./Shopify";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const refetch=vi.fn(async()=>({}));
const sync=vi.fn(async()=>({ok:true}));
vi.mock("../app/DashboardDataContext",()=>({useDashboardSnapshot:()=>({snapshot:{fetchedAt:"x"},daily:[{metric_date:"2026-08-10",shopify_net_revenue:100,shopify_gross_revenue:110,shopify_orders:2,shopify_paid_orders:2,shopify_customers:2,shopify_refunds:10}],products:[{metric_date:"2026-08-10",product_id:"p1",product_title:"Produto",variant:"",quantity:2,net_revenue:100}],sources:[{provider:"shopify",last_success_at:"2026-08-10",data_max_available:"2026-08-10"}],campaigns:[],loading:false,refreshing:false,error:null,refetch})}));
vi.mock("../app/api",()=>({
  refreshProviderData:(...args:unknown[])=>sync(...args),
  getShopifyReport:vi.fn(async()=>({
    ok:true,client_id:"amalie",period:{start:"2026-08-10",end:"2026-08-10",days:1},
    summary:{revenue_total:110,net_revenue:100,orders:2,average_ticket:50,customers:2,paid_orders:2,cancelled_orders:0,refunds_count:1,refunded_amount:10,refunds_occurred_in_period_count:1,refunds_occurred_in_period_amount:10},
    trends:{daily:[]},recent_orders:[{shopify_order_id:"1",customer_name:"Cliente",financial_status:"paid",total_price:50,currency:"BRL",items_count:1}],top_products:[],
    technical:{last_success_at:"2026-08-10",last_received_at:"2026-08-10",processed_count:1,error_count:0,recent_errors:[],recent_webhooks:[]},
  })),
  getShopifyCustomers:vi.fn(async()=>({
    ok:true,client_id:"amalie",period:{start:"2026-08-10",end:"2026-08-10",days:1},count:2,
    summary:{total_customers:2,recurring_customers:1,multi_order_customers:1},
    items:[{customer_key:"A",name:"Cliente A",email:null,total_orders:2,total_spent:100,average_ticket:50,last_purchase_at:"2026-08-10",first_purchase_at:"2026-08-01",status:"recurring",all_time_orders:3}],
  })),
}));
vi.mock("../app/PeriodContext",()=>({usePeriod:()=>({period:{start:"2026-08-10",end:"2026-08-10"},periodDays:1,setCurrentMonthPeriod:vi.fn(),setMonthPeriod:vi.fn(),setPresetPeriod:vi.fn()})}));
vi.mock("../app/activeClient",()=>({getActiveClientId:()=>"amalie",getActiveClientName:()=>"Amalie",MUGO_APP_NAME:"Mugô Dados"}));
vi.mock("../app/syncOrchestrator",()=>({describeSyncError:()=>"erro",isSyncAlreadyRunningError:()=>false,runExclusiveSync:(_key:unknown,run:()=>Promise<unknown>)=>run()}));

test("renderiza KPIs Shopify do read model e atualização manual preserva/refaz snapshot",async()=>{const node=document.createElement("div"),root=createRoot(node);document.body.appendChild(node);await act(async()=>root.render(<Shopify canSync onLogout={vi.fn()} onOpenDashboard={vi.fn()}/>));expect(node.textContent).toContain("100");expect(node.textContent).toContain("Cliente A");expect(node.textContent).not.toContain("Ainda não há pedidos da Shopify neste período.");const button=[...node.querySelectorAll("button")].find(item=>item.textContent==="Atualizar dados");await act(async()=>button?.dispatchEvent(new MouseEvent("click",{bubbles:true})));expect(sync).toHaveBeenCalledWith("shopify",{start:"2026-08-10",end:"2026-08-10"});expect(refetch).toHaveBeenCalledTimes(1);act(()=>root.unmount());node.remove();});

test("viewer: os números aparecem e a loja oferece Atualizar dados", async () => {
  sync.mockClear();
  const node = document.createElement("div");
  const root = createRoot(node);
  document.body.appendChild(node);
  await act(async () => root.render(<Shopify canSync={false} onLogout={vi.fn()} onOpenDashboard={vi.fn()} />));
  expect(node.textContent).toContain("Cliente A");
  expect([...node.querySelectorAll("button")].some((item) => item.textContent === "Atualizar dados")).toBe(true);
  expect(sync).not.toHaveBeenCalled();
  act(() => root.unmount());
  node.remove();
});
