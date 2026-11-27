import { useEffect, useState } from "react";
import { getOfficialPreview, listInstagramCreativePosts, searchMetaInterests, type AudienceRef, type BuilderOptions,
  type InstagramCreativePost, type MetaInterest } from "../../app/metaAds";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

/** Identidade do anúncio: a Página e o Instagram ligados à empresa (vêm da conexão, como no Gerenciador). */
export function MetaIdentity({ identity }: { identity: BuilderOptions["identity"] | null }) {
  if (!identity) return <p className="ds-caption">Carregando a Página e o Instagram da conta…</p>;
  return <div className="metaLevelBlock metaIdentity">
    <h3>Identidade</h3>
    <div className="metaIdentityRow">
      <span>{identity.page.picture ? <img src={identity.page.picture} alt="" /> : <i />}<b>Página do Facebook</b><small>{identity.page.name || identity.page.id}</small></span>
      <span>{identity.instagram?.picture ? <img src={identity.instagram.picture} alt="" /> : <i />}<b>Conta do Instagram</b>
        <small>{identity.instagram ? `@${identity.instagram.username || identity.instagram.id}` : "Não conectada: o anúncio usa a Página no Instagram"}</small></span>
    </div>
  </div>;
}

/** "Usar publicação existente": escolhe um post do Instagram da marca para virar o anúncio. */
export function MetaExistingPost({ value, disabled, onPick }: { value: string | null | undefined; disabled?: boolean; onPick: (id: string, image: string) => void }) {
  const [posts, setPosts] = useState<InstagramCreativePost[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    listInstagramCreativePosts().then((r) => { if (alive) setPosts(r.posts); })
      .catch((cause) => { if (alive) { setPosts([]); setError(message(cause, "Não foi possível ler os posts do Instagram.")); } });
    return () => { alive = false; };
  }, []);
  return <div className="metaLevelBlock">
    <h3>Publicação existente do Instagram</h3>
    <p className="ds-caption">A arte, a legenda, as curtidas e os comentários do post continuam no anúncio.</p>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {posts === null ? <p className="ds-caption">Carregando posts…</p> : !posts.length && !error ? <p className="ds-emptyLine">Nenhum post sincronizado do Instagram.</p> :
      <div className="metaExistingPosts" role="radiogroup" aria-label="Posts do Instagram">
        {posts.slice(0, 24).map((p) => <label key={p.id} className={value === p.id ? "is-selected" : ""}>
          <input type="radio" name="meta-existing-post" disabled={disabled} checked={value === p.id} onChange={() => onPick(p.id, p.image_url || p.preview_url)} />
          <img src={p.preview_url} alt={p.caption ? p.caption.slice(0, 80) : "Post do Instagram"} loading="lazy" />
          <small>{new Date(p.timestamp).toLocaleDateString("pt-BR")}</small>
        </label>)}
      </div>}
  </div>;
}

/** Segmentação detalhada: interesses da lista oficial da Meta (id exato), com os escritos antes como etiquetas. */
export function MetaInterestSearch({ refs, typed, disabled, onChange }: {
  refs: AudienceRef[]; typed: string[]; disabled?: boolean; onChange: (refs: AudienceRef[], typed: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState<MetaInterest[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (q.trim().length < 2) return;
    let alive = true;
    const handle = window.setTimeout(() => {
      setBusy(true); setError("");
      searchMetaInterests(q).then((r) => { if (alive) setFound(r.interests); })
        .catch((cause) => { if (alive) setError(message(cause, "Não foi possível buscar interesses na Meta.")); })
        .finally(() => { if (alive) setBusy(false); });
    }, 350);
    return () => { alive = false; window.clearTimeout(handle); };
  }, [q]);
  const chosen = new Set(refs.map((r) => r.id));
  const results = q.trim().length < 2 ? [] : found;
  const legacy = typed.filter((t) => t.trim() && !refs.some((r) => r.name.toLowerCase() === t.trim().toLowerCase()));
  return <div className="metaInterests">
    <label className="ds-field">Segmentação detalhada (interesses da Meta)
      <input type="search" disabled={disabled} value={q} placeholder="Buscar interesses, como Perfumes" onChange={(e) => setQ(e.target.value)} /></label>
    {busy ? <small className="ds-caption">Buscando na Meta…</small> : null}
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {results.length ? <ul className="metaInterestResults" aria-label="Interesses encontrados na Meta">
      {results.map((i) => <li key={i.id}><button type="button" disabled={disabled || chosen.has(i.id)}
        onClick={() => { onChange([...refs, { id: i.id, name: i.name }], typed); setQ(""); }}>
        <b>{i.name}</b><small>{[i.path, i.size].filter(Boolean).join(" · ")}</small></button></li>)}
    </ul> : null}
    {refs.length || legacy.length ? <div className="metaChips" aria-label="Interesses escolhidos">
      {refs.map((r) => <span key={r.id}>{r.name}<button type="button" disabled={disabled} aria-label={`Remover ${r.name}`}
        onClick={() => onChange(refs.filter((x) => x.id !== r.id), typed.filter((t) => t.toLowerCase() !== r.name.toLowerCase()))}>×</button></span>)}
      {legacy.map((t) => <span key={t} title="Escrito antes: a Meta procura pelo nome na hora de criar">{t}<button type="button" disabled={disabled} aria-label={`Remover ${t}`}
        onClick={() => onChange(refs, typed.filter((x) => x !== t))}>×</button></span>)}
    </div> : <small className="ds-caption">Sem interesses: público amplo.</small>}
  </div>;
}

/** Prévia oficial da Meta (a mesma do Gerenciador), por posicionamento. Precisa do rascunho salvo. */
export function MetaOfficialPreview({ draftId, formats, adIndex, version, save }: {
  draftId: string; formats: BuilderOptions["preview_formats"]; adIndex: number; version: string; save: () => Promise<unknown>;
}) {
  const [format, setFormat] = useState(formats[0]?.key || "INSTAGRAM_STANDARD");
  const [src, setSrc] = useState<string | null>(null);
  const [shownFor, setShownFor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = `${format}:${adIndex}:${version}`;
  async function load() {
    setBusy(true); setError("");
    try {
      await save();
      const r = await getOfficialPreview(draftId, format, adIndex);
      setSrc(r.src); setShownFor(key);
    } catch (cause) { setSrc(null); setError(message(cause, "Não foi possível gerar a prévia na Meta.")); } finally { setBusy(false); }
  }
  return <section className="metaLevelBlock metaOfficialPreview" aria-label="Prévia do anúncio">
    <div className="metaOfficialPreviewHead"><h3>Prévia do anúncio</h3>
      <label className="ds-field"><span className="ds-srOnly">Posicionamento</span>
        <select value={format} onChange={(e) => setFormat(e.target.value)}>
          {formats.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</select></label>
      <button type="button" className="ds-button" disabled={busy} onClick={() => void load()}>{busy ? "Gerando na Meta…" : error || (shownFor && shownFor !== key) ? "Atualizar prévia" : "Ver prévia oficial"}</button>
    </div>
    <p className="ds-caption">Gerada pela própria Meta, como no Gerenciador. Salva o rascunho antes e não cria nada na campanha.
      Vídeo: na primeira vez ele é enviado para a conta e a Meta leva alguns segundos para processar; a criação reaproveita o mesmo envio.</p>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {src ? <iframe className="metaOfficialPreviewFrame" title="Prévia oficial da Meta" src={src}
      sandbox="allow-scripts allow-same-origin allow-popups" referrerPolicy="no-referrer" /> : null}
  </section>;
}
