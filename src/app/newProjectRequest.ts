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
