// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { vi, test, expect } from "vitest";
import useExecutiveDashboard from "./useExecutiveDashboard";
vi.mock("../../app/DashboardDataContext",()=>({useDashboardSnapshot:()=>({snapshot:{fetchedAt:"x"},daily:[{metric_date:"2026-08-10",shopify_net_revenue:100,shopify_gross_revenue:110,shopify_orders:2,shopify_paid_orders:2,shopify_customers:2,shopify_refunds:10,meta_spend:20,meta_attributed_revenue:40,meta_purchases:1,google_ads_spend:5,google_ads_conversion_value:8}],sources:[],campaigns:[],products:[],loading:false,refreshing:false,error:null,refetch:vi.fn()})}));
function Harness(){const value=useExecutiveDashboard({isAuthenticated:true,activeClientId:"amalie",period:{start:"2026-08-10",end:"2026-08-10"}});return <div>{value.executiveData?.shopify?.net_revenue}:{value.executiveData?.total_paid_media.blended_roas}</div>}
test("deriva operação e retorno do mesmo snapshot",async()=>{const node=document.createElement("div"),root=createRoot(node);await act(async()=>root.render(<Harness/>));expect(node.textContent).toBe("100:4");act(()=>root.unmount());});
