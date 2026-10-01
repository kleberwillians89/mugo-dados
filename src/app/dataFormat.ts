// Formatação de leitura de dados (pt-BR). Só apresentação: nunca altera o
// valor calculado — o valor exato continua disponível onde a forma curta é
// usada (title / tooltip / tabelas).

const currencyExact = new Intl.NumberFormat("pt-BR", {
  style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const currencyWhole = new Intl.NumberFormat("pt-BR", {
  style: "currency", currency: "BRL", minimumFractionDigits: 0, maximumFractionDigits: 0,
});
const currencyCompact = new Intl.NumberFormat("pt-BR", {
  style: "currency", currency: "BRL", notation: "compact", minimumFractionDigits: 0, maximumFractionDigits: 1,
});
const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 1 });

function safe(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** Valor exato: R$ 48.320,00 */
export function formatCurrency(value: unknown): string {
  return currencyExact.format(safe(value));
}

/** Leitura rápida: R$ 48,3 mil · R$ 1,2 mi · R$ 298 · R$ 12,50 */
export function formatCurrencyShort(value: unknown): string {
  const n = safe(value);
  const abs = Math.abs(n);
  if (abs >= 10_000) return currencyCompact.format(n);
  if (abs >= 100 || n === 0) return currencyWhole.format(n);
  return currencyExact.format(n);
}

/** Rótulos de eixo: R$ 4 mil · R$ 800 */
export function formatCurrencyAxis(value: unknown): string {
  const n = safe(value);
  return Math.abs(n) >= 1_000 ? currencyCompact.format(n) : currencyWhole.format(n);
}

export function formatInteger(value: unknown): string {
  return integer.format(safe(value));
}

/** 18,4 (sem o sinal de %) */
export function formatPercentNumber(value: unknown): string {
  return oneDecimal.format(safe(value));
}

const CALENDAR_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/**
 * Datas de calendário (YYYY-MM-DD) são exibidas como estão — sem conversão
 * de fuso, que deslocaria o dia (ex.: 2026-09-01 virando 31/08).
 */
export function formatCalendarDate(value: string, style: "day" | "month" | "long" = "day"): string {
  const match = CALENDAR_DATE.exec(String(value || "").trim());
  if (!match) return String(value || "");
  const [, year, month, day] = match;
  if (style === "month") return `${MONTHS_SHORT[Number(month) - 1]}/${year.slice(2)}`;
  if (style === "long") return `${day}/${month}/${year}`;
  return `${day}/${month}`;
}

/** Intervalo do filtro: "02/09/2026 – 01/10/2026" (um dia: "01/10/2026"). */
export function formatCalendarRange(start: string, end: string): string {
  if (!start || !end) return "";
  const first = formatCalendarDate(start, "long");
  const last = formatCalendarDate(end, "long");
  return first === last ? first : `${first} – ${last}`;
}

const MONTHS_LONG = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

/** Por extenso, sem conversão de fuso: "12 de setembro" · "setembro de 2026". */
export function formatCalendarDateWords(value: string, style: "day" | "month" = "day"): string {
  const match = CALENDAR_DATE.exec(String(value || "").trim());
  if (!match) return String(value || "");
  const [, year, month, day] = match;
  const monthName = MONTHS_LONG[Number(month) - 1];
  return style === "month" ? `${monthName} de ${year}` : `${Number(day)} de ${monthName}`;
}

/**
 * O único ponto mais alto de uma série (> 0). Empate ou série curta não têm
 * destaque objetivo: retorna null e o título continua descritivo.
 */
export function uniquePeak<T>(rows: T[], valueOf: (row: T) => number): T | null {
  if (rows.length < 2) return null;
  let best: T | null = null;
  let max = -Infinity;
  let ties = 0;
  for (const row of rows) {
    const value = Number(valueOf(row));
    if (!Number.isFinite(value)) continue;
    if (value > max) {
      max = value;
      best = row;
      ties = 1;
    } else if (value === max) {
      ties += 1;
    }
  }
  return best && max > 0 && ties === 1 ? best : null;
}

/** Data e hora no fuso comercial (America/Sao_Paulo): 30/09/2026, 14:20 */
export function formatDateTimeSaoPaulo(value: string | null | undefined): string {
  const parsed = new Date(String(value || ""));
  if (Number.isNaN(parsed.getTime())) return String(value || "");
  return parsed.toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: "America/Sao_Paulo",
  });
}

const compactInteger = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const ratio = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Contagens em eixo e leitura rápida: 12,4 mil · 1,2 mi · 840 */
export function formatCompactInteger(value: unknown): string {
  return compactInteger.format(safe(value));
}

/** Retorno sobre investimento: 4,50x */
export function formatRatio(value: unknown): string {
  return `${ratio.format(safe(value))}x`;
}

/** Percentual já em pontos: 2,35% */
export function formatPercent(value: unknown, digits = 2): string {
  return `${safe(value).toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
}
