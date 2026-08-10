// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { vi, test, expect } from "vitest";
import useDashboardPaid from "./useDashboardPaid";
const refetch=vi.fn();
vi.mock("../../app/DashboardDataContext",()=>({useDashboardSnapshot:(start?:string)=>({snapshot:{fetchedAt:"2026-08-10",daily:[]},loading:false,refreshing:false,error:null,refetch,sources:[{provider:"meta",last_success_at:"2026-08-10"}],campaigns:[],products:[],daily:start==="2026-08-10"?[{metric_date:"2026-08-10",meta_spend:10,meta_attributed_revenue:30,meta_purchases:1,meta_impressions:100,meta_reach:90,meta_clicks:5,meta_link_clicks:4,meta_video_views:2}]:[]} )}));
function Harness({start}:{start:string}){const value=useDashboardPaid({isAuthenticated:true,activeClientId:"amalie",period:{start,end:"2026-08-10"}});return <div>{value.paidData?.totals.spend}</div>}
test("filtra o snapshot local sem chamar Render ou refetch",async()=>{const node=document.createElement("div"),root=createRoot(node);await act(async()=>root.render(<Harness start="2026-08-10"/>));expect(node.textContent).toBe("10");await act(async()=>root.render(<Harness start="2026-08-01"/>));expect(node.textContent).toBe("0");expect(refetch).not.toHaveBeenCalled();act(()=>root.unmount());});
