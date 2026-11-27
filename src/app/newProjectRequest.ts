import type { ProjectKind } from "./projects";

/** "Criar planejamento" (Planejar) abre o formulário direto: pedido por ?novo=1 ou pela marca de sessão. Lido uma vez. */
export const NEW_PROJECT_FLAG = "mugo:projects:new";
export function requestNewProject(kind: ProjectKind) {
  try { window.sessionStorage.setItem(NEW_PROJECT_FLAG, kind); } catch { /* sem sessionStorage: abre a lista normal */ }
}
export function takeNewProjectRequest(kind: ProjectKind): boolean {
  let asked = false;
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.get("novo") === "1") {
      asked = true;
      url.searchParams.delete("novo");
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    }
    if (window.sessionStorage.getItem(NEW_PROJECT_FLAG) === kind) { asked = true; window.sessionStorage.removeItem(NEW_PROJECT_FLAG); }
  } catch { /* navegador sem storage: segue sem abrir */ }
  return asked;
}

/** "Definir metas" (Planejar) abre o Planejamento já na seção Metas (#metas ou pedido de sessão). Lido uma vez. */
export const GOALS_SECTION_FLAG = "mugo:planning:goals";
export function requestGoalsSection() {
  try { window.sessionStorage.setItem(GOALS_SECTION_FLAG, "1"); } catch { /* sem sessionStorage: abre no topo */ }
}
export function takeGoalsSectionRequest(): boolean {
  let asked = false;
  try {
    if (window.location.hash === "#metas") asked = true;
    if (window.sessionStorage.getItem(GOALS_SECTION_FLAG) === "1") { asked = true; window.sessionStorage.removeItem(GOALS_SECTION_FLAG); }
  } catch { /* navegador sem storage */ }
  return asked;
}

/** Atalho de Lançar campanha para uma área do WhatsApp (Disparos em massa ou Modelos), lido uma vez ao abrir a tela. */
const WHATSAPP_AREA_KEY = "mugo:whatsapp:area";
export type WhatsAppArea = "bulk" | "models";
export function requestWhatsAppArea(area: WhatsAppArea) {
  try { window.sessionStorage.setItem(WHATSAPP_AREA_KEY, area); } catch { /* sem storage: abre em Conversas */ }
}
export function takeWhatsAppArea(): WhatsAppArea | null {
  const fromUrl = new URLSearchParams(window.location.search).get("area");
  let stored: string | null = null;
  try { stored = window.sessionStorage.getItem(WHATSAPP_AREA_KEY); window.sessionStorage.removeItem(WHATSAPP_AREA_KEY); } catch { stored = null; }
  const area = fromUrl || stored;
  return area === "bulk" || area === "models" ? area : null;
}
