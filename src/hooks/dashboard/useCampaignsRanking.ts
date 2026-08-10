import { useCallback, useMemo } from "react";
import { useDashboardSnapshot } from "../../app/DashboardDataContext";
import type { CampaignsListResponse } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";

export default function useCampaignsRanking({ activeClientId, enabled=true, period }: { isAuthenticated:boolean;activeClientId:string;activeConnectionId?:string|null;enabled?:boolean;period?:DashboardPeriod|null }) {
  const safe=useMemo(()=>ensureDashboardPeriod(period),[period]);
  const model=useDashboardSnapshot(safe.start,safe.end);
  const campaignsData=useMemo<CampaignsListResponse|null>(()=>{
    if(!enabled||!activeClientId||(!model.snapshot&&model.loading))return null;
    const grouped=new Map<string,Record<string,number|string>>();
    for(const row of model.campaigns.filter(item=>item.provider==="meta")){
      const id=String(row.campaign_id);const current=grouped.get(id)||{campaign_id:id,campaign_name:String(row.campaign_name||id),spend:0,impressions:0,reach:0,clicks:0,conversions:0,revenue:0,last_stat_date:""};
      for(const key of ["spend","impressions","reach","clicks","conversions","revenue"] as const)current[key]=Number(current[key]||0)+Number(row[key]||0);
      current.last_stat_date=String(row.metric_date);grouped.set(id,current);
    }
    const campaigns=[...grouped.values()].map(row=>{const spend=Number(row.spend),impressions=Number(row.impressions),clicks=Number(row.clicks),revenue=Number(row.revenue);return {...row,cpc:clicks?spend/clicks:0,cpm:impressions?spend*1000/impressions:0,ctr:impressions?clicks*100/impressions:0,roas:spend?revenue/spend:null};}).sort((a,b)=>Number((b as Record<string,unknown>).spend)-Number((a as Record<string,unknown>).spend)).slice(0,8);
    return {ok:true,client_id:activeClientId,date_range:{since:safe.start,until:safe.end},campaigns:campaigns as CampaignsListResponse["campaigns"],total:campaigns.length};
  },[activeClientId,enabled,model.campaigns,model.loading,model.snapshot,safe.end,safe.start]);
  const reloadCampaigns=useCallback(()=>model.refetch() as Promise<unknown> as Promise<CampaignsListResponse|null>,[model]);
  return {campaignsData,loadingCampaigns:model.loading&&!campaignsData,campaignsError:model.error,reloadCampaigns};
}
