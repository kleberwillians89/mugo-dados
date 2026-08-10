import { useCallback, useMemo } from "react";
import type { Ga4ReportResponse } from "../../app/types";
import { useDashboardSnapshot } from "../../app/DashboardDataContext";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";

export default function useDashboardGa4({ activeClientId, period }: { isAuthenticated:boolean; activeClientId:string; period?:DashboardPeriod|null }) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const model = useDashboardSnapshot(safePeriod.start, safePeriod.end);
  const ga4Report = useMemo<Ga4ReportResponse | null>(() => {
    if (!activeClientId || (!model.snapshot && model.loading)) return null;
    const daily = model.daily.map((row) => ({ date:row.metric_date,sessions:Number(row.ga4_sessions||0),active_users:Number(row.ga4_users||0),total_users:Number(row.ga4_users||0),event_count:Number(row.ga4_events||0),ecommerce_purchases:Number(row.ga4_purchases||0),purchase_revenue:Number(row.ga4_revenue||0),total_revenue:Number(row.ga4_revenue||0),view_item_count:0,add_to_cart_count:0,begin_checkout_count:0,purchase_count:Number(row.ga4_purchases||0) }));
    const total = (key:keyof typeof daily[number]) => daily.reduce((value,row) => value + Number(row[key]||0),0);
    const source=model.sources.find((item)=>item.provider==="ga4");
    const emptyGroup=(key:string,title:string)=>({key,title,description:"",total_events:0,total_users:0,items:[]});
    return {ok:true,client_id:activeClientId,property_id:"read-model",period:{start:safePeriod.start,end:safePeriod.end,days:daily.length},
      summary:{sessions:total("sessions"),active_users:total("active_users"),total_users:total("total_users"),event_count:total("event_count"),purchases:total("ecommerce_purchases"),purchase_revenue:total("purchase_revenue"),total_revenue:total("total_revenue"),average_daily_active_users:daily.length?total("active_users")/daily.length:0,average_daily_total_users:daily.length?total("total_users")/daily.length:0},
      funnel:{view_item:0,add_to_cart:0,begin_checkout:0,add_payment_info:0,purchase:total("ecommerce_purchases")},
      commerce_journey:{summary:{view_item:0,add_to_cart:0,begin_checkout:0,add_payment_info:0,purchase:total("ecommerce_purchases"),add_to_cart_rate:0,checkout_rate:0,payment_info_rate:0,purchase_rate:0,purchase_rate_from_view_item:0},items:[]},
      behavior:emptyGroup("behavior","Comportamento"),engagement:emptyGroup("engagement","Engajamento"),merchandising:emptyGroup("merchandising","Produtos"),trends:{daily},channels:[],campaigns:[],events:[],meta:{last_synced_at:source?.last_success_at||null,data_available:daily.length>0,daily_rows:daily.length,channel_rows:0,campaign_rows:0,event_rows:0}};
  },[activeClientId,model.daily,model.loading,model.snapshot,model.sources,safePeriod.end,safePeriod.start]);
  const reloadGa4=useCallback(async(options?:{force?:boolean})=>{void options;return model.refetch() as Promise<unknown> as Promise<Ga4ReportResponse|null>;},[model]);
  return {ga4Report,loadingGa4:model.loading&&!ga4Report,refreshingGa4:model.refreshing,ga4Error:model.error,ga4UpdatedAt:model.snapshot?.fetchedAt||null,reloadGa4};
}
