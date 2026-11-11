import { useCallback, useEffect, useRef, useState } from "react";
import { cancelAgentRun, continueAgentRun, getAgentRun, startAgentRun, type AgentRun, type AgentStep } from "../../app/contentOps";

const ICON: Record<string, string> = { pendente: "○", rodando: "◐", feito: "✓", falhou: "✕" };
const POLL_MS = 4000;
const WEEK_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8];

const errorText = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

/**
 * Esteira de agentes (equipe) em duas fases:
 * 1. pesquisa (dados, voz do público, produtos, saúde da marca, concorrentes) → Matriz do período → PARA na Matriz;
 * 2. a equipe confere a Matriz e clica em "Gerar conteúdo" → redação → revisão de marca → Calendário →
 *    briefing de arte → Revisão interna.
 * Pedido com a esteira ocupada (Briefing → Social Media, por exemplo) entra na fila e roda na ordem.
 */
export default function AgentPipeline({ clientId, onDone, onOpenCalendar }: { clientId: string; onDone?: () => void; onOpenCalendar?: () => void }) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"start" | "continue" | "cancel" | null>(null);
  const [open, setOpen] = useState(false);
  const [weeks, setWeeks] = useState(4);
  const [focus, setFocus] = useState("");
  const lastStatus = useRef<string | null>(null);

  const apply = useCallback((next: AgentRun | null) => {
    const before = lastStatus.current;
    lastStatus.current = next?.status ?? null;
    setRun(next);
    if (next?.status === "rodando" || next?.status === "aguardando") setOpen(true);
    // Avisa a tela quando a esteira muda de fase: a Matriz nova aparece na pausa; os posts, no fim.
    if (before === "rodando" && next && next.status !== "rodando") onDone?.();
  }, [onDone]);

  const load = useCallback(async () => {
    try {
      const r = await getAgentRun();
      setSteps(r.steps || []); apply(r.run);
    } catch { /* tela segue; o botão mostra o erro ao rodar */ }
  }, [apply]);

  useEffect(() => { lastStatus.current = null; void load(); }, [clientId, load]);
  useEffect(() => {
    if (run?.status !== "rodando" && !(run?.queued && run.queued > 0)) return;
    const timer = window.setInterval(() => { void load(); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [run?.status, run?.queued, load]);

  async function act(kind: "start" | "continue" | "cancel", fn: () => Promise<{ run: AgentRun; steps: AgentStep[] }>, fallback: string) {
    setBusy(kind); setError(null);
    try {
      const r = await fn();
      setSteps(r.steps || []);
      if (r.run.status === "na_fila") { await load(); setError(null); }
      else { lastStatus.current = r.run.status === "cancelada" ? null : lastStatus.current; apply(r.run); }
      if (kind === "cancel") await load();
    } catch (cause) { setError(errorText(cause, fallback)); }
    finally { setBusy(null); }
  }

  const status = run?.status;
  const running = status === "rodando";
  const waiting = status === "aguardando";
  const shown = (run?.steps?.length ? run.steps : steps.map((s) => ({ ...s, status: "pendente" as const })));
  const when = run?.created_at ? new Date(run.created_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : null;
  const queued = run?.queued || 0;
  const runWeeks = run?.options?.weeks;

  return <section className="agentPipeline" aria-label="Esteira de agentes">
    <header className="agentPipelineHead">
      <div>
        <h3>Esteira de agentes</h3>
        <p>A IA lê tudo da marca (dados, material enviado, voz do público, produtos, saúde da marca e concorrentes) e monta a <b>Matriz</b> do período.
          A esteira <b>para na Matriz</b> para vocês conferirem; no <b>Gerar conteúdo</b>, ela escreve, revisa, agenda e manda para a <b>Revisão interna</b>. A arte é com vocês.</p>
      </div>
      <div className="agentPipelineActions">
        {run && !running && !waiting ? <button type="button" className="ds-link" onClick={() => setOpen(!open)}>{open ? "Esconder" : "Ver última execução"}</button> : null}
        <label className="matrixPick"><span>Período</span><select aria-label="Semanas da esteira" value={weeks} disabled={Boolean(busy)} onChange={(e) => setWeeks(Number(e.target.value))}>
          {WEEK_OPTIONS.map((n) => <option key={n} value={n}>{n} semana{n > 1 ? "s" : ""}</option>)}</select></label>
        <button type="button" className="ds-button is-primary" disabled={Boolean(busy)}
          onClick={() => void act("start", () => startAgentRun({ ...(weeks !== 4 ? { weeks } : {}), ...(focus.trim() ? { focus: focus.trim() } : {}) }), "Não foi possível iniciar a esteira.")}>
          {busy === "start" ? "Iniciando…" : running || waiting ? "Pôr na fila" : "Rodar esteira de agentes"}</button>
      </div>
    </header>
    <label className="agentFocus"><span>Foco ou briefing (opcional)</span>
      <textarea rows={2} maxLength={1000} value={focus} placeholder="Ex.: lançamento do Oud Royal até o Natal, sem falar de desconto"
        disabled={Boolean(busy)} onChange={(e) => setFocus(e.target.value)} /></label>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {queued ? <p className="libHint" role="status">{queued} pedido{queued > 1 ? "s" : ""} na fila: começa{queued > 1 ? "m" : ""} quando esta esteira terminar.</p> : null}
    {open && shown.length ? <>
      <ol className="agentSteps">{shown.map((s) => <li key={s.key} className={`is-${s.status || "pendente"}`}>
        <span className="agentIcon" aria-hidden="true">{ICON[s.status || "pendente"]}</span>
        <div><b>{s.agent}</b><small>{s.detail || s.task}</small></div>
      </li>)}</ol>
      {running ? <p className="libHint" role="status">Leva alguns minutos. Pode sair desta tela: a esteira continua sozinha.</p> : null}
      {waiting ? <div className="agentPause" role="status">
        <p><b>⏸ Matriz pronta{runWeeks ? ` (${runWeeks} semana${runWeeks > 1 ? "s" : ""})` : ""}.</b> Confira abaixo: edite, selecione ou descarte as pautas.
          Se selecionar alguma, só as selecionadas viram conteúdo; senão, todas as que não foram descartadas.</p>
        <div className="agentPauseActions">
          <button type="button" className="ds-button is-primary" disabled={Boolean(busy)}
            onClick={() => void act("continue", () => continueAgentRun(run!.id), "Não foi possível continuar a esteira.")}>
            {busy === "continue" ? "Gerando…" : "Gerar conteúdo"}</button>
          <button type="button" className="ds-link" disabled={Boolean(busy)}
            onClick={() => void act("cancel", () => cancelAgentRun(run!.id), "Não foi possível cancelar.")}>
            {busy === "cancel" ? "Cancelando…" : "Parar aqui (a Matriz fica salva)"}</button>
        </div>
      </div> : null}
      {status === "concluida" ? <p className="studioOk" role="status">✓ {run?.summary}{when ? ` (${when})` : ""}
        {onOpenCalendar ? <> <button type="button" className="ds-link" onClick={onOpenCalendar}>Abrir o Calendário</button></> : null}</p> : null}
      {status === "cancelada" ? <p className="libHint" role="status">Esteira parada na Matriz. A Matriz continua salva para usar à mão.</p> : null}
      {status === "falhou" ? <p className="studioError" role="alert">{run?.error || "A esteira parou no meio."} O que já foi feito ficou salvo na Matriz e no Calendário.</p> : null}
    </> : null}
  </section>;
}
