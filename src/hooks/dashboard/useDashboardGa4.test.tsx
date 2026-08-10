// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { vi, test, expect } from "vitest";
import useDashboardGa4 from "./useDashboardGa4";
vi.mock("../../app/DashboardDataContext",()=>({useDashboardSnapshot:()=>({snapshot:{fetchedAt:"x"},daily:[{metric_date:"2026-08-10",ga4_sessions:20,ga4_users:12,ga4_events:40,ga4_purchases:2,ga4_revenue:90}],sources:[],campaigns:[],products:[],loading:false,refreshing:false,error:null,refetch:vi.fn()})}));
function Harness(){const value=useDashboardGa4({isAuthenticated:true,activeClientId:"amalie",period:{start:"2026-08-01",end:"2026-08-10"}});return <div>{value.ga4Report?.summary.sessions}</div>}
test("adapta GA4 diretamente do read model",async()=>{const node=document.createElement("div"),root=createRoot(node);await act(async()=>root.render(<Harness/>));expect(node.textContent).toBe("20");act(()=>root.unmount());});
