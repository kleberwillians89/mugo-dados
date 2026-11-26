import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { listBriefs, type Brief } from "../../app/briefs";
import { CREATIVE_DIRECTION_FIELDS, basedOnText, suggestCreativeDirection, type BasedOn, type CreativeDirection as Direction } from "../../app/studio";

type Field = (typeof CREATIVE_DIRECTION_FIELDS)[number]["key"];
type Props = {
  value: Direction;
  onChange: (next: Direction) => void;
  /** Pauta salva: a IA usa a pauta, a marca e as referências dela. Nova pauta: só escrita livre. */
  itemId?: string | null;
  disabled?: boolean;
  /** O direcionamento mudou e ainda não foi salvo. */
  pending?: boolean;
  /** Pauta que veio da Matriz: o briefing da Matriz já acompanha a tarefa quando nenhum outro é escolhido. */
  fromMatrix?: boolean;
  /** Dentro do Briefing da peça: sem cabeçalho próprio. */
  embedded?: boolean;
  /** Só a ajuda da IA e o briefing de referência (os campos ficam na página do briefing). */
  aiOnly?: boolean;
};

const message = (cause: unknown) => (cause instanceof Error && cause.message ? cause.message : "A IA não respondeu agora.");

/**
 * Direcionamento Criativo da peça: orientação específica para quem vai criar (título/conceito, textos, referências,
 * instruções). Escrita livre, com ajuda opcional da IA: a sugestão aparece ao lado e só entra no texto quando a pessoa
 * escolhe "Usar", "Substituir" ou "Acrescentar". Salva junto com a pauta. Não substitui o briefing nem a Matriz.
 */
export default function CreativeDirection({ value, onChange, itemId, disabled, pending, fromMatrix, embedded, aiOnly }: Props) {
  const [briefs, setBriefs] = useState<Brief[] | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<{ text: Direction; based_on: BasedOn } | null>(null);

  useEffect(() => {
    let alive = true;
    listBriefs().then((r) => { if (alive) setBriefs(r.briefs); }).catch(() => { if (alive) setBriefs([]); });
    return () => { alive = false; };
  }, []);

  const set = (key: Field | "brief_id", text: string) => onChange({ ...value, [key]: text });
  const current = (key: Field) => (value[key] || "").trim();
  const suggested = suggestion ? CREATIVE_DIRECTION_FIELDS.filter((f) => (suggestion.text[f.key] || "").trim()) : [];
  const take = (key: Field, mode: "replace" | "append") => {
    const text = (suggestion?.text[key] || "").trim();
    if (!text) return;
    const oneLine = CREATIVE_DIRECTION_FIELDS.find((f) => f.key === key)?.rows === 1;
    set(key, mode === "append" && current(key) ? `${(value[key] || "").trimEnd()}${oneLine ? " " : "\n"}${text}` : text);
    setSuggestion((s) => (s ? { ...s, text: { ...s.text, [key]: "" } } : s));
  };
  const fillEmpty = () => {
    if (!suggestion) return;
    const next = { ...value };
    for (const { key } of CREATIVE_DIRECTION_FIELDS) if (!current(key) && (suggestion.text[key] || "").trim()) next[key] = (suggestion.text[key] || "").trim();
    onChange(next); setSuggestion(null);
  };

  async function suggest() {
    if (!itemId || busy) return;
    setBusy(true); setError(null);
    try { const r = await suggestCreativeDirection(itemId, value, instruction); setSuggestion({ text: r.suggestion, based_on: r.based_on }); }
    catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }

  const selected = value.brief_id || "";
  const knownBrief = !selected || (briefs || []).some((b) => b.id === selected);

  const body = <>
    <div className="postBriefingForm">
      {aiOnly ? null : CREATIVE_DIRECTION_FIELDS.map((f) => <label key={f.key}>{f.label}
        {f.rows === 1
          ? <input maxLength={f.max} value={value[f.key] || ""} placeholder={f.placeholder} disabled={disabled} onChange={(e) => set(f.key, e.target.value)} />
          : <textarea rows={f.rows} maxLength={f.max} value={value[f.key] || ""} placeholder={f.placeholder} disabled={disabled} onChange={(e) => set(f.key, e.target.value)} />}
      </label>)}
      <label>Briefing de referência
        <select value={selected} disabled={disabled || briefs === null} onChange={(e) => onChange({ ...value, brief_id: e.target.value || null })}>
          <option value="">{briefs === null ? "Carregando…" : fromMatrix ? "O da Matriz (se houver)" : "Nenhum"}</option>
          {!knownBrief ? <option value={selected}>Briefing escolhido antes</option> : null}
          {(briefs || []).map((b) => <option key={b.id} value={b.id}>{b.brief.title}</option>)}
        </select>
        <small>Vai junto na tarefa como referência. O direcionamento desta peça continua valendo.</small>
      </label>
    </div>
    <div className="postBriefingActions">
      <input className="aiAssistInstruction" maxLength={600} value={instruction} disabled={disabled || !itemId}
        placeholder="Pedido opcional para a IA (ex.: mais objetivo, focar no lançamento)" aria-label="Pedido para a IA" onChange={(e) => setInstruction(e.target.value)} />
      <button type="button" className="ds-button" disabled={disabled || busy || !itemId} onClick={() => void suggest()}>
        <Sparkles className="uiGlyph" size={14} aria-hidden="true" /> {busy ? "Sugerindo…" : "Sugerir com IA"}</button>
    </div>
    {!itemId ? <small className="postArtHint">Crie a pauta para pedir sugestão à IA. A escrita livre já vale.</small> : null}
    {error ? <small role="alert" className="studioError">{error}</small> : null}
    {suggestion ? <div className="aiResult" aria-label="Sugestão da IA">
      <p className="aiBasis">Sugestão da IA: nada muda no seu texto até você escolher. {basedOnText(suggestion.based_on)}</p>
      {suggested.map((f) => <div key={f.key} className="aiOption">
        <b>{f.label}</b>
        <p className="aiText">{suggestion.text[f.key]}</p>
        <div className="postBriefingActions">
          {current(f.key) ? <>
            <button type="button" className="ds-button" onClick={() => take(f.key, "append")}>Acrescentar ao meu texto</button>
            <button type="button" className="ds-button" onClick={() => take(f.key, "replace")}>Substituir o meu texto</button>
          </> : <button type="button" className="ds-button is-primary" onClick={() => take(f.key, "replace")}>Usar</button>}
        </div>
      </div>)}
      <div className="postBriefingActions">
        {suggested.some((f) => !current(f.key)) ? <button type="button" className="ds-button" onClick={fillEmpty}>Preencher só os campos vazios</button> : null}
        <button type="button" className="ds-button" onClick={() => setSuggestion(null)}>Descartar sugestão</button>
      </div>
    </div> : null}
    {pending ? <small className="postArtHint is-pending">O direcionamento mudou. Clique em <b>Salvar alterações</b>, aqui embaixo, para valer.</small> : null}
  </>;
  if (embedded) return <div className="postDirection" aria-label="Direcionamento Criativo">{body}</div>;
  return <details className="postFromMatrix postBriefing postDirection" open aria-label="Direcionamento Criativo">
    <summary>Direcionamento Criativo</summary>
    <p className="postBriefingEmpty">Orientação desta peça para quem vai criar. Escreva livremente, peça ajuda à IA ou combine os dois. Não substitui o briefing da campanha nem a Matriz.</p>
    {body}
  </details>;
}
