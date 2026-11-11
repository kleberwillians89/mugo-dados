import { useCallback, useEffect, useRef, useState } from "react";
import { getAgentRun, startAgentRun, type AgentRun, type AgentStep } from "../../app/contentOps";

const ICON: Record<string, string> = { pendente: "○", rodando: "◐", feito: "✓", falhou: "✕" };
const POLL_MS = 4000;

/**
 * Esteira de agentes (equipe): um clique roda pesquisa → estratégia → redação → briefing visual → revisão de marca →
 * Calendário → revisão interna. A tela acompanha cada agente ao vivo. A arte fica com a equipe (briefing em cada post).
 */
export default function AgentPipeline({ clientId, onDone, onOpenCalendar }: { clientId: string; onDone?: () => void; onOpenCalendar?: () => void }) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [open, setOpen] = useState(false);
  const wasRunning = useRef(false);

  const load = useCallback(async () => {
    try {
      const r = await getAgentRun();
      setSteps(r.steps || []); setRun(r.run);
      if (r.run?.status === "rodando") { wasRunning.current = true; setOpen(true); }
      else if (wasRunning.current) { wasRunning.current = false; onDone?.(); }
    } catch { /* tela segue; o botão mostra o erro ao rodar */ }
  }, [onDone]);

  useEffect(() => { wasRunning.current = false; void load(); }, [clientId, load]);
  useEffect(() => {
    if (run?.status !== "rodando") return;
    const timer = window.setInterval(() => { void load(); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [run?.status, load]);

  async function start() {
    setStarting(true); setError(null);
    try {
      const r = await startAgentRun();
      setRun(r.run); setSteps(r.steps || []); setOpen(true); wasRunning.current = true;
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível iniciar a esteira."); }
    finally { setStarting(false); }
  }

  const running = run?.status === "rodando";
  const shown = (run?.steps?.length ? run.steps : steps.map((s) => ({ ...s, status: "pendente" as const })));
  const when = run?.created_at ? new Date(run.created_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : null;

  return <section className="agentPipeline" aria-label="Esteira de agentes">
    <header className="agentPipelineHead">
      <div>
        <h3>Esteira de agentes</h3>
        <p>A IA faz o mês de ponta a ponta: pesquisa, estratégia, textos e briefing visual, revisão de marca e agenda no Calendário. Tudo chega em <b>Revisão interna</b> para a equipe; a arte é com vocês.</p>
      </div>
      <div className="agentPipelineActions">
        {run && !running ? <button type="button" className="ds-link" onClick={() => setOpen(!open)}>{open ? "Esconder" : "Ver última execução"}</button> : null}
        <button type="button" className="ds-button is-primary" disabled={starting || running} onClick={() => void start()}>
          {running ? "Rodando…" : starting ? "Iniciando…" : "Rodar esteira de agentes"}</button>
      </div>
    </header>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {open && shown.length ? <>
      <ol className="agentSteps">{shown.map((s) => <li key={s.key} className={`is-${s.status || "pendente"}`}>
        <span className="agentIcon" aria-hidden="true">{ICON[s.status || "pendente"]}</span>
        <div><b>{s.agent}</b><small>{s.detail || s.task}</small></div>
      </li>)}</ol>
      {running ? <p className="libHint" role="status">Leva alguns minutos. Pode sair desta tela: a esteira continua e os posts aparecem no Calendário.</p> : null}
      {run?.status === "concluida" ? <p className="studioOk" role="status">✓ {run.summary}{when ? ` (${when})` : ""}
        {onOpenCalendar ? <> <button type="button" className="ds-link" onClick={onOpenCalendar}>Abrir o Calendário</button></> : null}</p> : null}
      {run?.status === "falhou" ? <p className="studioError" role="alert">{run.error || "A esteira parou no meio."} O que já foi feito ficou salvo na Matriz e no Calendário.</p> : null}
    </> : null}
  </section>;
}
