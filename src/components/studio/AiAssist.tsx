import { useState } from "react";
import { ASSIST_ACTIONS, basedOnText, runAssist, type AssistAction, type AssistResponse, type StudioFormat } from "../../app/studio";

type Draft = { format: StudioFormat; title: string; pillar: string; hook: string; caption_draft: string; date?: string; time?: string };
type Props = {
  draft: Draft;
  disabled?: boolean;
  /** Aplica o texto escolhido no rascunho da pauta (a pessoa ainda salva depois). */
  onApply: (patch: Partial<Pick<Draft, "hook" | "caption_draft">>) => void;
};

const message = (cause: unknown) => (cause instanceof Error && cause.message ? cause.message : "A IA não respondeu agora.");

/** Motores de redação no modal: tudo parte dos dados da marca e volta para revisão humana. */
export default function AiAssist({ draft, disabled, onApply }: Props) {
  const [busy, setBusy] = useState<AssistAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [out, setOut] = useState<AssistResponse | null>(null);
  const [copied, setCopied] = useState(false);

  async function run(action: AssistAction) {
    if (busy || !draft.title.trim()) return;
    setBusy(action); setError(null);
    try {
      setOut(await runAssist(action, { format: draft.format, title: draft.title, pillar: draft.pillar || undefined, hook: draft.hook || undefined,
        caption_draft: draft.caption_draft || undefined, scheduled_at: draft.date ? `${draft.date}T${draft.time || "12:00"}:00-03:00` : undefined }, instruction));
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }

  const appendHashtags = (tags: string[]) => onApply({ caption_draft: `${draft.caption_draft.trimEnd()}\n\n${tags.join(" ")}`.trim() });
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 2000); } catch { /* texto visível */ }
  }

  return <details className="aiAssist">
    <summary>✦ IA de conteúdo <small>usa os dados da marca</small></summary>
    <div className="aiAssistBody">
      <div className="aiAssistActions">
        {(Object.keys(ASSIST_ACTIONS) as AssistAction[]).filter((a) => a !== "roteiro_reels" || ["reels", "stories", "video"].includes(draft.format))
          .map((a) => <button key={a} type="button" className="ds-button" disabled={disabled || Boolean(busy) || !draft.title.trim()} onClick={() => void run(a)}>
            {busy === a ? "Gerando…" : ASSIST_ACTIONS[a]}</button>)}
      </div>
      <input className="aiAssistInstruction" maxLength={600} value={instruction} placeholder="Pedido opcional (ex.: mais curto, falar do lançamento, tom divertido)"
        onChange={(e) => setInstruction(e.target.value)} disabled={disabled} />
      {!draft.title.trim() ? <p className="postArtHint">Dê um título à pauta para usar a IA.</p> : null}
      {error ? <p role="alert" className="studioError">{error}</p> : null}
      {out ? <div className="aiResult">
        <p className="aiBasis">{basedOnText(out.based_on)}</p>
        {out.flags.length ? <p className="studioError">⚠ Revise: {out.flags.join(", ")}</p> : null}
        {out.action === "legenda" ? <>
          <p className="aiText">{out.result.caption}</p>
          <p className="aiWhy">{out.result.why}</p>
          <button type="button" className="ds-button is-primary" onClick={() => onApply({ caption_draft: out.result.caption })}>Usar como legenda</button>
        </> : null}
        {out.action === "revisar" ? <>
          <ul className="aiList">{out.result.issues.map((i, n) => <li key={n}><b>{i.problem}</b> → {i.fix}</li>)}</ul>
          <p className="aiText">{out.result.improved_caption}</p>
          <button type="button" className="ds-button is-primary" onClick={() => onApply({ caption_draft: out.result.improved_caption })}>Usar versão revisada</button>
        </> : null}
        {out.action === "variacoes" ? <>
          {out.result.variations.map((v, n) => <div key={n} className={`aiOption ${n === out.result.recommended_index ? "is-recommended" : ""}`}>
            <span className="studioChip">{v.angle}{n === out.result.recommended_index ? " · recomendada" : ""}</span>
            <p className="aiText">{v.caption}</p>
            <button type="button" className="ds-button" onClick={() => onApply({ caption_draft: v.caption })}>Usar esta</button>
          </div>)}
          <p className="aiWhy">{out.result.why}</p>
        </> : null}
        {out.action === "ganchos" ? <ul className="aiList">{out.result.hooks.map((h, n) => <li key={n}>
          <span>{h.hook} <small>({h.angle})</small></span>
          <button type="button" className="studioLink" onClick={() => onApply({ hook: h.hook })}>Usar</button></li>)}</ul> : null}
        {out.action === "hashtags" ? <>
          <p className="aiText">{out.result.hashtags.join(" ")}</p>
          <p className="aiWhy">{out.result.why}</p>
          <button type="button" className="ds-button" onClick={() => appendHashtags(out.result.hashtags)}>Adicionar à legenda</button>
        </> : null}
        {out.action === "roteiro_reels" ? <>
          <p className="aiWhy">≈ {out.result.duration_seconds}s · Capa: “{out.result.cover_text}” · Áudio: {out.result.audio_suggestion}</p>
          <ol className="aiScenes">{out.result.scenes.map((s, n) => <li key={n}><b>{s.seconds}</b> {s.visual}
            {s.text_on_screen ? <span className="aiScreen">Texto: {s.text_on_screen}</span> : null}
            {s.voiceover ? <span className="aiVoice">Fala: {s.voiceover}</span> : null}</li>)}</ol>
          <button type="button" className="ds-button" onClick={() => void copy(out.result.scenes.map((s) => `${s.seconds} — ${s.visual}${s.text_on_screen ? ` | Texto: ${s.text_on_screen}` : ""}${s.voiceover ? ` | Fala: ${s.voiceover}` : ""}`).join("\n"))}>
            {copied ? "Roteiro copiado ✓" : "Copiar roteiro"}</button>
          {out.result.scenes[0]?.text_on_screen ? <button type="button" className="studioLink" onClick={() => onApply({ hook: out.result.scenes[0].text_on_screen })}>Usar 1ª cena como gancho</button> : null}
        </> : null}
      </div> : null}
    </div>
  </details>;
}
