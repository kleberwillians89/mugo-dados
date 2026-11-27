import type { CalendarItem } from "../../app/studio";

/** O que aconteceu com a publicação, em poucas palavras (aparece no próprio dia do calendário). */
export function publishState(item: CalendarItem): { tone: "ok" | "wait" | "bad" | "info"; label: string } | null {
  const at = (iso?: string | null) => iso ? new Date(iso).toLocaleTimeString("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" }) : "";
  switch (item.publish_status) {
    case "publicado": return { tone: "ok", label: `Publicado ${at(item.published_at)}`.trim() };
    case "publicando": return { tone: "wait", label: "Publicando…" };
    case "falhou": return { tone: "bad", label: "Não publicou" };
    case "manual": return { tone: "bad", label: "Publicar à mão" };
    case "simulado": return { tone: "info", label: "Teste (simulado)" };
  }
  if (item.status === "publicado") return { tone: "ok", label: "Publicado à mão" };
  if (item.status === "aprovado" && item.schedule_confirmed_at) return { tone: "wait", label: "Agendado" };
  return null;
}

