/**
 * Agenda das atualizações automáticas (GitHub Actions, .github/workflows/sync-jobs.yml).
 * Horários em UTC, iguais ao cron do workflow. O GitHub pode atrasar alguns
 * minutos, por isso a tela fala em "por volta de".
 */
type Schedule = { minutes: number[]; hours: number[] | "all" };

const EVERY_3H = [0, 3, 6, 9, 12, 15, 18, 21];

export const AUTO_REFRESH_SCHEDULES: Record<string, Schedule> = {
  meta_ads: { minutes: [5], hours: "all" },
  instagram: { minutes: [10], hours: [6, 12, 18, 23] },
  instagram_content: { minutes: [10], hours: [6, 12, 18, 23] },
  ga4: { minutes: [20], hours: EVERY_3H },
  google_ads: { minutes: [35], hours: EVERY_3H },
  fbits: { minutes: [0, 30], hours: "all" },
  fbits_official: { minutes: [0, 30], hours: "all" },
  shopify: { minutes: [15, 45], hours: "all" },
};

export function nextAutoRefresh(provider: string, now: Date = new Date()): Date | null {
  const schedule = AUTO_REFRESH_SCHEDULES[provider];
  if (!schedule) return null;
  const cursor = new Date(now.getTime());
  cursor.setUTCSeconds(0, 0);
  for (let step = 0; step <= 26 * 60; step += 1) {
    cursor.setUTCMinutes(cursor.getUTCMinutes() + 1);
    const hourOk = schedule.hours === "all" || schedule.hours.includes(cursor.getUTCHours());
    if (hourOk && schedule.minutes.includes(cursor.getUTCMinutes())) return new Date(cursor.getTime());
  }
  return null;
}

const TZ = "America/Sao_Paulo";

function dayKey(date: Date) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

export function nextAutoRefreshLabel(provider: string, now: Date = new Date()): string | null {
  const next = nextAutoRefresh(provider, now);
  if (!next) return null;
  const time = new Intl.DateTimeFormat("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(next);
  const tomorrow = dayKey(next) !== dayKey(now);
  return `próxima execução automática prevista ${tomorrow ? "amanhã " : ""}por volta das ${time}`;
}
