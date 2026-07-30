import KpiCard from "./KpiCard";
import type {
  DashboardDailyRow,
  DashboardResponse,
  DashboardTotals,
} from "../app/types";

export type KpiKey =
  | "reach"
  | "profile_views"
  | "website_clicks"
  | "accounts_engaged"
  | "total_interactions"
  | "followers";

type Props = {
  kpis: Record<string, number>;
  dash?: DashboardResponse | null;
  currentFollowers?: number;
  active: KpiKey;
  setActive: (k: KpiKey) => void;
};

type DailyMetricKey = Exclude<keyof DashboardDailyRow, "date">;

function safe(n: unknown): number {
  return typeof n === "number" && Number.isFinite(n) ? n : 0;
}

function fmt(n: number): string {
  try {
    return n.toLocaleString("pt-BR");
  } catch {
    return String(n);
  }
}

function getDailyRows(dash: DashboardResponse | null | undefined): DashboardDailyRow[] {
  return Array.isArray(dash?.daily) ? dash.daily : [];
}

function sparkFromDaily(
  dash: DashboardResponse | null | undefined,
  key: DailyMetricKey,
  n = 14
): number[] {
  const daily = getDailyRows(dash);
  if (!daily.length) return [];
  const slice = daily.slice(Math.max(0, daily.length - n));
  return slice.map((d) => safe(d[key]));
}

function sparkFollowersDelta(
  dash: DashboardResponse | null | undefined,
  n = 14
): number[] {
  const daily = getDailyRows(dash);
  if (daily.length < 2) return [];
  const slice = daily.slice(Math.max(0, daily.length - (n + 1)));
  const out: number[] = [];
  for (let i = 1; i < slice.length; i++) {
    out.push(safe(slice[i].followers) - safe(slice[i - 1].followers));
  }
  return out.slice(-n);
}

export default function KpiGrid({
  kpis,
  dash,
  currentFollowers,
  active,
  setActive,
}: Props) {
  const daily = getDailyRows(dash);
  const lastDaily = daily.length ? daily[daily.length - 1] : null;
  const periodTotals = dash?.period_totals;

  const todayFromDash = (k: DailyMetricKey): number => safe(lastDaily?.[k]);
  const todayFromRefresh = (k: string): number => safe(kpis?.[k]);

  const today = (dashboardKey: DailyMetricKey, refreshKey?: string): number => {
    const v = todayFromDash(dashboardKey);
    if (v !== 0) return v;
    return todayFromRefresh(refreshKey || dashboardKey);
  };

  const periodTotal = (k: keyof DashboardTotals): number =>
    safe(periodTotals?.[k] ?? dash?.totals_last_days?.[k] ?? dash?.monthly_totals?.[k]);

  const deltaPct = (k: keyof DashboardTotals): number | undefined => {
    const growth = dash?.period_growth_percent || dash?.monthly_growth_percent;
    if (!dash?.ok || !growth) return undefined;
    return safe(growth[k]);
  };

  const todayInteractions = today("total_interactions");
  const monthInteractions = periodTotal("total_interactions");
  const deltaInteractions = deltaPct("total_interactions");

  const followersDeltaPct = dash?.ok
    ? safe(dash?.period_growth_percent?.followers ?? dash?.monthly_growth_percent?.followers)
    : undefined;
  const followersGrowthTotal = safe(
    periodTotals?.followers_growth ?? dash?.followers_growth_last_days
  );

  const followersTotalNow = (() => {
    const last = daily.length ? safe(daily[daily.length - 1]?.followers) : 0;
    if (last > 0) return last;
    return safe(currentFollowers);
  })();

  const sparkReach = sparkFromDaily(dash, "reach");
  const sparkProfile = sparkFromDaily(dash, "profile_views");
  const sparkClicks = sparkFromDaily(dash, "website_clicks");
  const sparkEngaged = sparkFromDaily(dash, "accounts_engaged");
  const sparkInteractions = sparkFromDaily(dash, "total_interactions");
  const sparkFollowers = sparkFollowersDelta(dash);

  return (
    <div className="kpiGrid">
      <KpiCard
        label="Alcance"
        monthValue={fmt(periodTotal("reach"))}
        todayValue={fmt(today("reach"))}
        deltaPct={deltaPct("reach")}
        spark={sparkReach}
        active={active === "reach"}
        onClick={() => setActive("reach")}
      />

      <KpiCard
        label="Visitas ao perfil"
        monthValue={fmt(periodTotal("profile_views"))}
        todayValue={fmt(today("profile_views"))}
        deltaPct={deltaPct("profile_views")}
        spark={sparkProfile}
        active={active === "profile_views"}
        onClick={() => setActive("profile_views")}
      />

      <KpiCard
        label="Cliques no link"
        monthValue={fmt(periodTotal("website_clicks"))}
        todayValue={fmt(today("website_clicks"))}
        deltaPct={deltaPct("website_clicks")}
        spark={sparkClicks}
        active={active === "website_clicks"}
        onClick={() => setActive("website_clicks")}
      />

      <KpiCard
        label="Contas engajadas"
        monthValue={fmt(periodTotal("accounts_engaged"))}
        todayValue={fmt(today("accounts_engaged"))}
        deltaPct={deltaPct("accounts_engaged")}
        spark={sparkEngaged}
        active={active === "accounts_engaged"}
        onClick={() => setActive("accounts_engaged")}
      />

      <KpiCard
        label="Interações"
        monthValue={fmt(monthInteractions)}
        todayValue={fmt(todayInteractions)}
        deltaPct={deltaInteractions}
        spark={sparkInteractions}
        active={active === "total_interactions"}
        onClick={() => setActive("total_interactions")}
      />

      <KpiCard
        label="Seguidores"
        monthValue={fmt(followersGrowthTotal)}
        todayValue={fmt(followersTotalNow)}
        deltaPct={followersTotalNow > 0 ? followersDeltaPct : undefined}
        spark={sparkFollowers}
        hint="Crescimento no período"
        active={active === "followers"}
        onClick={() => setActive("followers")}
      />
    </div>
  );
}
