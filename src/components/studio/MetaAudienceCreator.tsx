import { useState } from "react";
import { createAdAudience, type AccountAudience, type NewAudience } from "../../app/metaAds";

const KINDS: { id: NewAudience["kind"]; title: string; hint: string }[] = [
  { id: "instagram", title: "Engajou no Instagram", hint: "Quem interagiu com o Instagram da marca" },
  { id: "facebook", title: "Engajou no Facebook", hint: "Quem interagiu com a página da marca" },
  { id: "site", title: "Visitou o site", hint: "Pelo pixel; dá para filtrar por parte do link" },
  { id: "compradores", title: "Comprou no site", hint: "Pelo pixel (evento de compra)" },
  { id: "semelhante", title: "Semelhante", hint: "Pessoas parecidas com um público que já existe (Brasil)" },
  { id: "lista", title: "Clientes da loja", hint: "Lista da base do MUGOVERSO (só o hash vai para o Meta)" },
];
const IG_EVENTS = [["tudo", "Qualquer interação"], ["engajou", "Curtiu, comentou, salvou ou compartilhou"],
  ["visitou_perfil", "Visitou o perfil"], ["salvou", "Salvou post ou anúncio"]] as const;
const FB_EVENTS = [["tudo", "Qualquer interação"], ["visitou_perfil", "Visitou a página"]] as const;
const MAX_DAYS: Partial<Record<NewAudience["kind"], number>> = { instagram: 730, facebook: 730, site: 180, compradores: 180 };

/** Criar público na hora, sem abrir o Gerenciador. Sempre com o perfil da MARCA (evita o erro de público de parceiro). */
export default function MetaAudienceCreator({ sources, disabled, onCreated }: {
  sources: AccountAudience[]; disabled?: boolean; onCreated: (created: { id: string; name: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<NewAudience["kind"]>("instagram");
  const [event, setEvent] = useState("tudo");
  const [days, setDays] = useState(365);
  const [url, setUrl] = useState("");
  const [origin, setOrigin] = useState("");
  const [ratio, setRatio] = useState(1);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const max = MAX_DAYS[kind];
  const usableSources = sources.filter((a) => a.ready && a.kind !== "LOOKALIKE");

  async function create() {
    setBusy(true); setError(null); setNote(null);
    const input: NewAudience = { kind, ...(name.trim() ? { name: name.trim() } : {}) };
    if (kind === "instagram" || kind === "facebook") Object.assign(input, { event, days: Math.min(days, max!) });
    if (kind === "site") Object.assign(input, { days: Math.min(days, max!), ...(url.trim() ? { url_contains: url.trim() } : {}) });
    if (kind === "compradores") input.days = Math.min(days, max!);
    if (kind === "semelhante") Object.assign(input, { origin_audience_id: origin, ratio });
    try {
      const made = await createAdAudience(input);
      setNote(`Público "${made.name}" criado e já incluído. ${made.note}`);
      onCreated({ id: made.id, name: made.name });
      setName("");
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível criar o público.");
    } finally { setBusy(false); }
  }

  return <div className="metaAudCreate">
    <button type="button" className="ds-button" aria-expanded={open} disabled={disabled} onClick={() => setOpen(!open)}>
      {open ? "Fechar" : "+ Criar público"}</button>
    {open ? <div className="metaAudCreateBox">
      <div className="metaAudKinds" role="radiogroup" aria-label="Tipo de público">
        {KINDS.map((k) => <button key={k.id} type="button" role="radio" aria-checked={kind === k.id} className={kind === k.id ? "is-on" : ""}
          onClick={() => { setKind(k.id); setEvent("tudo"); setDays(k.id === "site" ? 30 : k.id === "compradores" ? 180 : 365); }}>
          <b>{k.title}</b><small>{k.hint}</small></button>)}
      </div>
      {kind === "instagram" || kind === "facebook" ? <label className="ds-field">Quem entra
        <select value={event} onChange={(e) => setEvent(e.target.value)}>
          {(kind === "instagram" ? IG_EVENTS : FB_EVENTS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select></label> : null}
      {max ? <label className="ds-field">Nos últimos (dias, até {max})
        <input type="number" min={1} max={max} value={days} onChange={(e) => setDays(Number(e.target.value) || 1)} /></label> : null}
      {kind === "site" ? <label className="ds-field">Só quem visitou páginas com (opcional)
        <input value={url} placeholder="Ex.: /colecao/legging" maxLength={200} onChange={(e) => setUrl(e.target.value)} /></label> : null}
      {kind === "semelhante" ? <>
        <label className="ds-field">Parecido com
          <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
            <option value="">Escolha um público de origem</option>
            {usableSources.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.size}</option>)}
          </select></label>
        <label className="ds-field">Tamanho: {ratio}% do Brasil ({ratio === 1 ? "mais parecido" : ratio >= 6 ? "mais alcance" : "equilíbrio"})
          <input type="range" min={1} max={10} value={ratio} onChange={(e) => setRatio(Number(e.target.value))} /></label>
      </> : null}
      <label className="ds-field">Nome (opcional)
        <input value={name} maxLength={120} placeholder="Deixe vazio para o nome automático" onChange={(e) => setName(e.target.value)} /></label>
      {error ? <p className="ds-caption metaAdsMissing" role="alert">{error}</p> : null}
      {note ? <p className="ds-caption" role="status">{note}</p> : null}
      <button type="button" className="ds-button is-primary" disabled={busy || disabled || (kind === "semelhante" && !origin)}
        onClick={() => void create()}>{busy ? "Criando no Meta…" : "Criar público no Meta"}</button>
    </div> : null}
  </div>;
}
