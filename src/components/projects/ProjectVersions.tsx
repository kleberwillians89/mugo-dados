import { useCallback, useEffect, useState, type ReactNode } from "react";
import { History } from "lucide-react";
import Drawer from "../Drawer";
import { PROJECT_COLUMNS, getProjectVersion, listProjectVersions, restoreProjectVersion, type Project, type ProjectKind,
  type ProjectVersion, type ProjectVersionSummary } from "../../app/projects";

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const stage = (s: string | null) => PROJECT_COLUMNS.find((c) => c.key === s)?.label || "";

/**
 * Versões do plano: número, data, autor e origem. Abrir mostra o conteúdo daquela versão; restaurar grava a atual
 * e cria uma versão nova com o conteúdo antigo (nada é apagado).
 */
export default function ProjectVersions({ kind, project, onRestored, renderPlan, disabled }: { kind: ProjectKind; project: Project;
  onRestored: (p: Project) => void; renderPlan: (plan: Project["plan"]) => ReactNode; disabled?: boolean }) {
  const [versions, setVersions] = useState<ProjectVersionSummary[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState<ProjectVersion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { const r = await listProjectVersions(kind, project.id); setVersions(r.versions); setAvailable(r.available); }
    catch { setVersions([]); }
  }, [kind, project.id]);
  // Recarrega quando o plano muda (IA refez, aprovou, restaurou).
  useEffect(() => { const t = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(t); }, [load, project.updated_at, project.status]);

  async function show(v: number) {
    setError(null);
    try { setShown((await getProjectVersion(kind, project.id, v)).version); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível abrir a versão."); }
  }
  async function restore(v: ProjectVersion) {
    if (!window.confirm(`Voltar o conteúdo da versão ${v.version}? O plano atual fica guardado como versão e nada é apagado.`)) return;
    setBusy(true); setError(null);
    try { const r = await restoreProjectVersion(kind, project.id, v.version); onRestored(r.project); setShown(null); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível restaurar."); }
    finally { setBusy(false); }
  }

  const current = versions?.[0];
  return <>
    <button type="button" className="ds-button projVersionsButton" disabled={disabled} onClick={() => { setOpen(true); void load(); }}>
      <History size={16} aria-hidden="true" /> {current ? `Versão ${current.version}` : "Versões"}
    </button>
    <Drawer open={open} width="lg" title={shown ? `Versão ${shown.version} · ${shown.origin_label}` : "Versões do plano"}
      description={shown ? `${shown.author} · ${when(shown.created_at)}${shown.note ? ` · ${shown.note}` : ""}` : "Refazer com IA, aprovar ou restaurar cria uma versão nova. As anteriores ficam guardadas."}
      onClose={() => { if (!busy) { setOpen(false); setShown(null); } }}
      footer={shown ? <>
        <button type="button" className="ds-button" disabled={busy} onClick={() => setShown(null)}>Voltar à lista</button>
        <button type="button" className="ds-button is-primary" disabled={busy || current?.version === shown.version} onClick={() => void restore(shown)}>
          {busy ? "Restaurando…" : current?.version === shown.version ? "Esta é a versão atual" : "Restaurar esta versão"}</button>
      </> : undefined}>
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {!available ? <p className="libHint">O histórico de versões ainda não está ativo nesta instalação.</p> : null}
      {shown ? <div className="projVersionPlan">{renderPlan(shown.plan)}</div>
        : versions && !versions.length && available ? <p className="libHint">Ainda sem versões. A primeira é gravada quando a IA gerar ou refazer o plano.</p>
        : <ol className="projVersionList">{(versions || []).map((v, index) => <li key={v.version}>
          <button type="button" onClick={() => void show(v.version)}>
            <strong>Versão {v.version}{index === 0 ? " · atual" : ""}</strong>
            <span>{v.origin_label}{v.status ? ` · ${stage(v.status)}` : ""}</span>
            <small>{v.author} · {when(v.created_at)}{v.note ? ` · ${v.note}` : ""}</small>
          </button>
        </li>)}</ol>}
    </Drawer>
  </>;
}
