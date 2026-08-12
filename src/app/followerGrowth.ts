import type { DashboardDailyMetric } from "./DashboardDataContext";

export type FollowerGrowth = {
  current: number | null;
  delta: number | null;
  percent: number | null;
  label: string | null;
};

function formatShortDate(value: string) {
  const [, month, day] = value.split("-");
  return `${day}/${month}`;
}

export function followerGrowthForPeriod(
  rows: DashboardDailyMetric[],
  start: string,
  end: string
): FollowerGrowth {
  const snapshots = rows
    .filter((row) => row.instagram_followers != null)
    .sort((left, right) => left.metric_date.localeCompare(right.metric_date));
  const inPeriod = snapshots.filter((row) => row.metric_date >= start && row.metric_date <= end);
  const currentRow = inPeriod.at(-1);
  if (!currentRow) return { current: null, delta: null, percent: null, label: null };

  const prior = snapshots.filter((row) => row.metric_date < start).at(-1);
  const baseline = prior || (inPeriod.length >= 2 ? inPeriod[0] : null);
  if (!baseline) {
    return { current: Number(currentRow.instagram_followers), delta: null, percent: null, label: null };
  }

  const current = Number(currentRow.instagram_followers);
  const previous = Number(baseline.instagram_followers);
  return {
    current,
    delta: current - previous,
    percent: previous > 0 ? ((current - previous) / previous) * 100 : null,
    label: prior ? "no período" : `desde ${formatShortDate(baseline.metric_date)}`,
  };
}
