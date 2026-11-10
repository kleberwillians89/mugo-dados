import type { TimelineEvent } from "../../app/studio";

export const DONE_KINDS = ["publicado", "pedido", "comentario_mugo", "referencia"];

/** Novidades feitas pela equipe depois da última vez que a pessoa olhou. */
export function newDone(events: TimelineEvent[], seenAt: string): number {
  return events.filter((e) => DONE_KINDS.includes(e.kind) && (!seenAt || e.at > seenAt)).length;
}
