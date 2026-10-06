import { useCallback, useMemo } from "react";
import type { DashboardDailyMetric } from "../../app/DashboardDataContext";
import { useDashboardSnapshot } from "../../app/DashboardDataContext";
import type { ExecutiveDashboardResponse, ExecutivePeriodPayload } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import { countUniqueShopifyCustomers } from "../../app/shopifyReadModel";

const n=(value:unknown)=>Number(value??0);
const total=(rows:DashboardDailyMetric[],key:keyof DashboardDailyMetric)=>rows.reduce((sum,row)=>sum+n(row[key]),0);
function shiftDate(value:string,days:number){const date=new Date(`${value}T00:00:00Z`);date.setUTCDate(date.getUTCDate()+days);return date.toISOString().slice(0,10);}
function buildPeriod(rows:DashboardDailyMetric[],start:string,end:string,sources:ReturnType<typeof useDashboardSnapshot>["sources"]):ExecutivePeriodPayload {
  const selected=rows.filter(row=>row.metric_date>=start&&row.metric_date<=end);
  const days=Math.max(1,Math.round((Date.parse(end)-Date.parse(start))/86400000)+1);
  const shopifyNet=total(selected,"shopify_net_revenue"),shopifyGross=total(selected,"shopify_gross_revenue"),orders=total(selected,"shopify_orders"),refunds=total(selected,"shopify_refunds");
  const metaSpend=total(selected,"meta_spend"),metaRevenue=total(selected,"meta_attributed_revenue"),googleSpend=total(selected,"google_ads_spend"),googleRevenue=total(selected,"google_ads_conversion_value");
  const source=(provider:string)=>sources.find(item=>item.provider===provider);
  const shopifyDaily=selected.filter(r=>r.shopify_orders!=null||r.shopify_net_revenue!=null).map(r=>({date:r.metric_date,gross_revenue:n(r.shopify_gross_revenue),net_revenue:n(r.shopify_net_revenue),orders:n(r.shopify_orders),paid_orders:n(r.shopify_paid_orders),cancelled_orders:0,refund_amount:n(r.shopify_refunds),average_order_value:n(r.shopify_orders)>0?n(r.shopify_net_revenue)/n(r.shopify_orders):0}));
  const metaDaily=selected.filter(r=>r.meta_spend!=null).map(r=>({date:r.metric_date,spend:n(r.meta_spend),attributed_revenue:n(r.meta_attributed_revenue),purchases:n(r.meta_purchases),roas:n(r.meta_spend)>0?n(r.meta_attributed_revenue)/n(r.meta_spend):null}));
  const paidSpend=metaSpend+googleSpend;
  return {period:{start,end,days},shopify:{connected:Boolean(source("shopify")||shopifyDaily.length),last_success_at:source("shopify")?.last_success_at||null,data_min_in_period:shopifyDaily[0]?.date||null,data_max_in_period:shopifyDaily.at(-1)?.date||null,data_max_available:source("shopify")?.data_max_available||null,gross_revenue:shopifyGross,net_revenue:shopifyNet,orders,paid_orders:total(selected,"shopify_paid_orders"),cancelled_orders:0,refunds:refunds>0?1:0,refunded_amount:refunds,refunds_occurred_in_period_count:refunds>0?1:0,refunds_occurred_in_period_amount:refunds,average_order_value:orders>0?shopifyNet/orders:0,new_customers:countUniqueShopifyCustomers(selected),returning_customers:0,daily:shopifyDaily},
    meta:{connected:Boolean(source("meta")||metaDaily.length),last_success_at:source("meta")?.last_success_at||null,data_max_available:source("meta")?.data_max_available||null,data_available:metaDaily.length>0,spend:metaSpend,attributed_revenue:metaRevenue,roas:metaSpend>0?metaRevenue/metaSpend:null,daily:metaDaily},
    google_ads:{connected:Boolean(source("google_ads")||selected.some(r=>r.google_ads_spend!=null)),data_available:selected.some(r=>r.google_ads_spend!=null),data_max_available:source("google_ads")?.data_max_available||null,spend:googleSpend,conversion_value:googleRevenue,attributed_revenue:googleRevenue,roas:googleSpend>0?googleRevenue/googleSpend:null},
    total_paid_media:{paid_media_spend:paidSpend,included_paid_sources:[...(metaSpend?['meta']:[]),...(googleSpend?['google_ads']:[])],blended_roas:paidSpend>0?shopifyNet/paidSpend:null},
    ga4:{connected:Boolean(source("ga4")||selected.some(r=>r.ga4_sessions!=null)),last_success_at:source("ga4")?.last_success_at||null,data_max_available:source("ga4")?.data_max_available||null,data_available:selected.some(r=>r.ga4_sessions!=null),sessions:total(selected,"ga4_sessions"),users:null,users_status:"unavailable",daily_user_sum:total(selected,"ga4_users"),user_count_semantics:"sum_of_daily_users",purchases:total(selected,"ga4_purchases"),revenue:total(selected,"ga4_revenue")},
    instagram:{connected:Boolean(source("instagram")||selected.some(r=>r.instagram_reach!=null)),last_success_at:source("instagram")?.last_success_at||null,data_max_available:source("instagram")?.data_max_available||null},
    daily:selected.map(r=>{const spend=n(r.meta_spend)+n(r.google_ads_spend);return {date:r.metric_date,shopify:shopifyDaily.find(d=>d.date===r.metric_date)||null,meta:metaDaily.find(d=>d.date===r.metric_date)||null,connected_paid_spend:spend,blended_roas:spend>0?n(r.shopify_net_revenue)/spend:null};})};
}

export default function useExecutiveDashboard({activeClientId,enabled=true,period}: {isAuthenticated:boolean;activeClientId:string;enabled?:boolean;period?:DashboardPeriod|null}) {
  const safe=useMemo(()=>ensureDashboardPeriod(period),[period]);
  const days=Math.max(1,Math.round((Date.parse(safe.end)-Date.parse(safe.start))/86400000)+1);
  const previousEnd=shiftDate(safe.start,-1),previousStart=shiftDate(previousEnd,-days+1);
  const model=useDashboardSnapshot(safe.start,safe.end);
  const previousModel=useDashboardSnapshot(previousStart,previousEnd);
  const executiveData=useMemo<ExecutiveDashboardResponse|null>(()=>{
    if(!activeClientId||!enabled||(!model.snapshot&&model.loading))return null;

    const current=buildPeriod(model.daily,safe.start,safe.end,model.sources),previous=buildPeriod(previousModel.daily,previousStart,previousEnd,previousModel.sources);
    const delta=(a:number|null,b:number|null,field:keyof DashboardDailyMetric)=>{
      const comparable=model.daily.some(row=>row[field]!=null)&&previousModel.daily.some(row=>row[field]!=null);
      return {absolute:!comparable||a==null||b==null?null:a-b,percent:!comparable||a==null||b==null||b===0?null:(a-b)/b*100};
    };
    return {...current,ok:true,client_id:activeClientId,previous_period:previous,deltas:{shopify_net_revenue:delta(current.shopify?.net_revenue??null,previous.shopify?.net_revenue??null,"shopify_net_revenue"),shopify_orders:delta(current.shopify?.orders??null,previous.shopify?.orders??null,"shopify_orders"),meta_spend:delta(current.meta.spend,previous.meta.spend,"meta_spend"),meta_roas:delta(current.meta.roas,previous.meta.roas,"meta_spend"),blended_roas:delta(current.total_paid_media.blended_roas,previous.total_paid_media.blended_roas,"shopify_net_revenue")}};
  },[activeClientId,enabled,model.daily,model.loading,model.snapshot,model.sources,previousModel.daily,previousModel.sources,previousStart,previousEnd,safe.end,safe.start]);
  const reloadExecutive=useCallback(async(options?:{force?:boolean})=>{void options;return model.refetch() as Promise<unknown> as Promise<ExecutiveDashboardResponse|null>;},[model]);
  return {executiveData,loadingExecutive:model.loading&&!executiveData,executiveError:model.error,reloadExecutive};
}
