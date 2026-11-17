import { useEffect, useState } from "react";
import { Lightbulb } from "lucide-react";
import { confirmLearning, getContextHealth, suggestLearning, type LearningSuggestion } from "../../app/brandContext";

/**
 * Aprender com o uso: ajustes, comentários e reescritas do cliente, o que ele aprovou e o que os consumidores
 * perguntam no WhatsApp viram fatos sugeridos para a memória da marca. A IA só roda no clique; só os fatos
 * marcados entram na memória (que vai em todos os prompts).
 */
export default function BrandLearning({ onLearned }: { onLearned?: () => void }) {
  const [signals, setSignals] = useState<number | null>(null);
  const [result, setResult] = useState<LearningSuggestion | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<"suggest" | "confirm" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => { getContextHealth().then((h) => setSignals(h.learning.new_signals)).catch(() => setSignals(null)); }, []);

  async function search() {
    setBusy("suggest"); setError(null); setDone(null);
    try {
      const res = await suggestLearning();
      setResult(res); setEdits({});
      setSelected(new Set(res.facts.map((f, i) => (f.confianca === "alta" ? i : -1)).filter((i) => i >= 0)));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível buscar aprendizados agora."); }
    finally { setBusy(null); }
  }

  async function save() {
    if (!result) return;
    const facts = result.facts.map((f, i) => (selected.has(i) ? (edits[i] ?? f.fato).trim() : "")).filter((f) => f.length >= 5);
    if (!facts.length) return;
    setBusy("confirm"); setError(null);
    try {
      const res = await confirmLearning(facts);
      setDone(`${res.saved} aprendizado(s) entraram na memória da marca. A IA já usa nas próximas pautas, briefings e respostas.`);
      setResult(null); setSignals(0);
      onLearned?.();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar."); }
    finally { setBusy(null); }
  }

  return <section className="bcCard bcLearning" aria-labelledby="bc-learning-title" data-testid="brand-learning">
    <header className="bcCardHead"><div>
      <h2 id="bc-learning-title"><Lightbulb size={18} aria-hidden="true" /> Aprender com o uso</h2>
      <p className="libHint">A IA lê os ajustes e comentários do cliente, os textos que ele reescreveu, o que aprovou e o que os consumidores
        perguntam no WhatsApp, e sugere o que guardar na memória da marca. Nada entra sem você marcar.</p>
    </div>
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void search()}>
        {busy === "suggest" ? "Lendo os sinais…" : signals ? `Buscar aprendizados (${signals} sinais novos)` : "Buscar aprendizados"}</button>
    </header>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {done ? <p role="status" className="studioOk">{done}</p> : null}
    {result && !result.facts.length ? <p className="libHint" role="status">{result.message}</p> : null}
    {result && result.facts.length ? <div className="bcLearnList">
      <p className="libHint">{result.facts.length} sugestão(ões) a partir de {result.signals} sinal(is). Os de confiança alta já vêm marcados; ajuste o texto se precisar.</p>
      {result.facts.map((fact, i) => <div key={i} className={`bcField${selected.has(i) ? " is-checked" : ""}`} data-fact={i}>
        <div className="bcFieldHead">
          <label><input type="checkbox" checked={selected.has(i)} onChange={() => setSelected((cur) => { const next = new Set(cur); if (next.has(i)) next.delete(i); else next.add(i); return next; })} />
            <b>{fact.origem_rotulo}</b></label>
          <span className={`bcBadge ${fact.confianca === "alta" ? "is-found" : "is-ambiguous"}`}>{fact.confianca === "alta" ? "Padrão claro" : "Conferir"}</span>
        </div>
        <textarea rows={2} maxLength={300} value={edits[i] ?? fact.fato} aria-label={`Aprendizado ${i + 1}`}
          onChange={(e) => setEdits((cur) => ({ ...cur, [i]: e.target.value }))} />
        {fact.evidencia ? <blockquote className="bcSource">“{fact.evidencia}”</blockquote> : null}
      </div>)}
      <div className="kbRow">
        <button type="button" className="ds-button is-primary" disabled={!selected.size || Boolean(busy)} onClick={() => void save()}>
          {busy === "confirm" ? "Guardando…" : `Guardar ${selected.size} na memória`}</button>
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => setResult(null)}>Descartar</button>
      </div>
    </div> : null}
  </section>;
}
