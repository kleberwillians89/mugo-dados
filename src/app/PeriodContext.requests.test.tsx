// @vitest-environment jsdom
import React, {act} from "react";
import {createRoot} from "react-dom/client";
import {expect,test,vi} from "vitest";
import {PeriodProvider,usePeriod} from "./PeriodContext";
import PeriodSelector from "../components/data/PeriodSelector";
import useGoals from "../hooks/useGoals";
import {getGoals} from "./goals";
import useDashboardSummary from "../hooks/dashboard/useDashboardSummary";
import {DashboardDataContext, type DashboardSnapshot} from "./DashboardDataContext";
const requests=vi.hoisted(()=>vi.fn(async(period:{start:string;end:string})=>({media:[],has_more:false,period})));
vi.mock("./api",async original=>({...await original<typeof import("./api")>(),getMedia:requests,getComments:vi.fn(async()=>({comments:[],total:0,top_words:[]}))}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
vi.mock("./activeClient",()=>({getActiveClientId:()=>"atomic-period-fixture"}));
vi.mock("./goals",()=>({getGoals:vi.fn(async()=>({client_id:"atomic-period-fixture",goals:[]}))}));

test("PeriodContext real: Dia→7→30→90 em StrictMode faz somente um período final por ação; metas base/full legítimos",async()=>{
  const values=new Map<string,string>();
  vi.stubGlobal("localStorage",{getItem:(key:string)=>values.get(key)||null,setItem:(key:string,value:string)=>values.set(key,value),removeItem:(key:string)=>values.delete(key)});
  localStorage.setItem("mugo.period",JSON.stringify({start:"2026-10-06",end:"2026-10-06"}));
  const snapshot={daily:[],sources:[],campaigns:[],products:[],fetchedAt:"fixture",queryCount:0} as DashboardSnapshot;
  function ReadComposition(){
    const {period}=usePeriod();
    useGoals("atomic-period-fixture",period.start,period.end);
    useDashboardSummary({isAuthenticated:true,activeClientId:"atomic-period-fixture",activeConnectionId:"fixture-organic",period,secondaryEnabled:true,commentsEnabled:true});
    return <PeriodSelector/>;
  }
  const node=document.createElement("div"),root=createRoot(node);
  await act(async()=>root.render(<React.StrictMode><PeriodProvider><DashboardDataContext.Provider value={{snapshot,loading:false,refreshing:false,error:null,refetch:async()=>snapshot}}><ReadComposition/></DashboardDataContext.Provider></PeriodProvider></React.StrictMode>));
  for(const label of ["7 dias","30 dias","90 dias"]){
    const button=[...node.querySelectorAll("button")].find(button=>button.textContent===label)!;
    await act(async()=>button.dispatchEvent(new MouseEvent("click",{bubbles:true})));
  }
  expect(requests).toHaveBeenCalledTimes(4);
  const periods=requests.mock.calls.map(call=>call[0]);
  expect(new Set(periods.map(period=>`${period.start}:${period.end}`)).size).toBe(4);
  expect(periods.map(period=>Math.round((Date.parse(period.end)-Date.parse(period.start))/86400000)+1)).toEqual([1,7,30,90]);
  expect(getGoals).toHaveBeenCalledTimes(8);
  for(const period of periods){
    expect(vi.mocked(getGoals).mock.calls.filter(call=>call[0]===period.start&&call[1]===period.end)).toHaveLength(2);
  }
  act(()=>root.unmount()); localStorage.removeItem("mugo.period"); vi.unstubAllGlobals();
});
