import type { CustomerValueResponse } from "../app/api";

const months = ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"];
const newC = [610, 420, 380, 455, 470, 520, 498, 530, 560, 590, 640, 410];
const ret = [120, 180, 190, 210, 230, 240, 255, 262, 280, 300, 330, 240];
const spend = [41000, 30000, 27000, 31000, 33000, 36000, 35500, 37000, 39500, 41000, 45500, 28000];
export const VALUE_FIXTURE: CustomerValueResponse = {
  ok: true, status: "ok", built_at: "2026-11-12T06:55:00Z", data_since: "2025-10-08T00:00:00Z", truncated: false, has_spend: true,
  months: months.map((m, i) => ({ month: m, new: newC[i], returning: ret[i], revenue_new: newC[i] * 230, revenue_returning: ret[i] * 210, spend: spend[i],
    cac: Math.round((spend[i] / newC[i]) * 100) / 100 })),
  cohorts: months.map((m, i) => {
    const age = months.length - 1 - i;
    const retention = Array.from({ length: age + 1 }, (_, k) => (k === 0 ? 100 : Math.max(3, Math.round((19 - k * 1.6 + (i % 3)) * 10) / 10)));
    let cum = 0;
    const ltv = retention.map((r, k) => { cum += k === 0 ? 232 : (r / 100) * 205; return Math.round(cum * 100) / 100; });
    return { month: m, size: newC[i], retention, ltv, cac: Math.round((spend[i] / newC[i]) * 100) / 100 };
  }),
  ltv: { "30": 251.4, "90": 302.8, "180": 356.1, "365": 431.9 }, ltv_basis: "receita", margin: null,
  summary: { customers: 6083, repeat_rate: 27.4, median_days_to_second: 48, cac_6m: 69.58, ltv_cac: 5.12, payback_months: 0, months_with_cac: 6 },
};
