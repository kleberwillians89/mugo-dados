import { Sparkles } from "lucide-react";
import { useState } from "react";
import { applySuggestion, dismissSuggestion, requestSuggestion, type CalendarItem } from "../../app/studio";

/**
 * Equipe: quando o cliente pede ajuste, a IA prepara a nova versão do post (gancho, legenda, roteiro e briefing visual)
 * a partir do comentário e das referências. Só sugere: a equipe aplica com um clique, pede outra ou descarta.
 */
export default function AiSuggestionCard({ item, onItemChange }: { item: CalendarItem; onItemChange: (item: CalendarItem) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const s = item.ai_suggestion;
  if (!s && item.status !== "rejeitado") return null;

  async function act(kind: "pedir" | "aplicar" | "descartar") {
    setBusy(kind); setError(null);
    try {
      if (kind === "aplicar") onItemChange((await applySuggestion(item.id)).item);
      else if (kind === "descartar") { await dismissSuggestion(item.id); onItemChange({ ...item, ai_suggestion: null }); }
      else onItemChange({ ...item, ai_suggestion: (await requestSuggestion(item.id)).suggestion });
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível concluir agora.");
    } finally { setBusy(null); }
  }

  if (!s) {
    return <div className="aiSuggestion is-empty">
      <p><b><Sparkles className="uiGlyph" size={14} aria-hidden="true" /> Ajuste pedido.</b> A IA pode preparar a nova versão a partir do comentário e das referências do cliente.</p>
      <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void act("pedir")}>{busy ? "Preparando…" : "Pedir sugestão à IA"}</button>
      {error ? <small className="studioError">{error}</small> : null}
    </div>;
  }
  return <div className="aiSuggestion" aria-label="Sugestão da IA para o ajuste">
    <p className="aiSuggestionHead"><b><Sparkles className="uiGlyph" size={14} aria-hidden="true" /> Sugestão da IA para o ajuste</b>{s.summary ? <span>{s.summary}</span> : null}</p>
    {s.note ? <p className="aiSuggestionNote">Pedido do cliente: “{s.note}”</p> : null}
    {s.hook ? <div><small>Gancho</small><p>{s.hook}</p></div> : null}
    {s.caption_draft ? <div><small>Legenda</small><p className="is-long">{s.caption_draft}</p></div> : null}
    {s.script ? <details><summary>Roteiro</summary><p className="is-long">{s.script}</p></details> : null}
    {s.visual_idea ? <div><small>Briefing visual (para a arte)</small><p>{s.visual_idea}</p></div> : null}
    <div className="aiSuggestionActions">
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void act("aplicar")}>{busy === "aplicar" ? "Aplicando…" : "Aplicar no post"}</button>
      <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void act("pedir")}>{busy === "pedir" ? "Preparando…" : "Outra versão"}</button>
      <button type="button" className="ds-button is-quiet" disabled={Boolean(busy)} onClick={() => void act("descartar")}>Descartar</button>
    </div>
    {error ? <small className="studioError">{error}</small> : null}
    <small className="libHint">Aplicar troca o texto do post e o briefing visual. A arte continua com a equipe.</small>
  </div>;
}
