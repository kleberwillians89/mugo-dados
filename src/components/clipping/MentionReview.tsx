import { useCallback, useEffect, useState } from "react";
import { CircleAlert } from "lucide-react";
import {
  SENTIMENT_NAME, SENTIMENT_ORDER, getMentions, reviewMention,
  type HealthSentiment, type Mention, type MentionShow, type MentionSource,
} from "../../app/brandHealth";
import SegmentedControl from "../data/SegmentedControl";

const SHOW: { id: MentionShow; label: string }[] = [
  { id: "todos", label: "Todos" }, { id: "negativo", label: "Negativos" }, { id: "misto", label: "Mistos" },
  { id: "positivo", label: "Positivos" }, { id: "sem_analise", label: "Sem análise" }, { id: "revisados", label: "Revisados" },
  { id: "fora", label: "Fora da avaliação" },
];
const when = (v: string | null) => (v ? new Date(v).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");

/** O "!" de um comentário: de onde veio e, para quem pode, a correção do que a IA entendeu. */
function MentionInfo({ m, canReview, onSaved, onClose }: {
  m: Mention; canReview: boolean; onSaved: (next: Mention) => void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(body: { sentiment?: HealthSentiment; excluded?: boolean; reset?: boolean }) {
    setBusy(true); setError(null);
    try {
      const out = await reviewMention(m.source, m.id, body);
      onSaved({ ...m, ...out });
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar a revisão.");
    } finally { setBusy(false); }
  }
  return <div className="bhMentionInfo" role="dialog" aria-label="De onde veio este comentário">
    <dl>
      <dt>Rede</dt><dd>Instagram · {m.source === "comments" ? "comentário no post" : "mensagem no Direct"}</dd>
      <dt>Quem</dt><dd>{m.author ?? "—"}</dd>
      <dt>Quando</dt><dd>{when(m.at)}</dd>
      {m.post ? <><dt>Post</dt><dd>{m.post.caption ?? "Post sem legenda"}{m.post.at ? ` · publicado ${when(m.post.at)}` : ""}
        {m.post.permalink ? <> · <a href={m.post.permalink} target="_blank" rel="noreferrer">abrir o post ↗</a></> : null}</dd></> : null}
      <dt>A IA entendeu</dt><dd>{m.sentiment_ai ? SENTIMENT_NAME[m.sentiment_ai] : "ainda sem análise"}{m.theme ? ` · assunto “${m.theme}”` : ""}</dd>
      {m.reviewed_at ? <><dt>Revisado</dt><dd>{when(m.reviewed_at)}</dd></> : null}
    </dl>
    {canReview ? <div className="bhMentionEdit">
      <label>Sentimento certo
        <select value={m.sentiment ?? ""} disabled={busy} onChange={(e) => void save({ sentiment: e.target.value as HealthSentiment })}>
          {!m.sentiment ? <option value="" disabled>Escolha</option> : null}
          {SENTIMENT_ORDER.map((s) => <option key={s} value={s}>{SENTIMENT_NAME[s]}</option>)}
        </select></label>
      <label className="bhCheck"><input type="checkbox" checked={!m.excluded} disabled={busy} onChange={(e) => void save({ excluded: !e.target.checked })} />
        Contar na avaliação da marca</label>
      {m.reviewed_at ? <button type="button" className="studioLink" disabled={busy} onClick={() => void save({ reset: true })}>Voltar ao que a IA disse</button> : null}
    </div> : <p className="bhMuted">Só a equipe pode corrigir a avaliação.</p>}
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    <button type="button" className="studioLink" onClick={onClose}>Fechar</button>
  </div>;
}

/** Comentários e Direct do período, um a um. Duplo sentido que a IA não pegou se corrige aqui. */
export default function MentionReview({ start, end, onChanged }: { start: string; end: string; onChanged?: () => void }) {
  const [source, setSource] = useState<MentionSource>("comments");
  const [show, setShow] = useState<MentionShow>("todos");
  const [items, setItems] = useState<Mention[]>([]);
  const [meta, setMeta] = useState({ hasMore: false, canReview: false, reviewEnabled: true, next: 0 });
  const [open, setOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (offset: number) => {
    setLoading(true); setError(null);
    try {
      const page = await getMentions({ start, end, source, show, offset });
      setItems((cur) => (offset ? [...cur, ...page.items] : page.items));
      setMeta({ hasMore: page.has_more, canReview: page.can_review, reviewEnabled: page.review_enabled, next: offset + 30 });
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar os comentários.");
    } finally { setLoading(false); }
  }, [start, end, source, show]);
  useEffect(() => { setOpen(null); void load(0); }, [load]);

  function saved(next: Mention) {
    setItems((cur) => cur.map((m) => (m.id === next.id ? next : m)));
    onChanged?.();
  }

  return <section className="bhCard bhMentions" aria-labelledby="bh-mentions">
    <h2 id="bh-mentions">Comentários e Direct, um a um</h2>
    <p className="bhSub">Clique no <b>!</b> para ver de onde veio. Se a IA não entendeu o duplo sentido, a equipe corrige o sentimento ou tira da avaliação da marca.</p>
    <div className="bhMentionsBar">
      <SegmentedControl ariaLabel="Canal" value={source} onSelect={(id) => setSource(id as MentionSource)}
        options={[{ id: "comments", label: "Comentários" }, { id: "direct", label: "Direct" }]} />
      <select aria-label="Mostrar" value={show} onChange={(e) => setShow(e.target.value as MentionShow)}>
        {SHOW.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </div>
    {!meta.reviewEnabled ? <p className="bhMuted">A revisão ainda não foi ativada no banco; por enquanto só dá para ver.</p> : null}
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {!loading && !items.length && !error ? <p className="bhMuted">Nada neste filtro no período.</p> : null}
    <ul className="bhMentionList">{items.map((m) => <li key={m.id} className={m.excluded ? "is-excluded" : ""}>
      <div className="bhMentionRow">
        <i className={`bhDot is-${m.sentiment ?? "sem_analise"}`} aria-hidden="true" />
        <div className="bhMentionText"><p>{m.text || <span className="bhMuted">(sem texto)</span>}</p>
          <small>{m.author ?? "—"} · {when(m.at)} · {m.sentiment ? SENTIMENT_NAME[m.sentiment] : "Sem análise"}
            {m.reviewed_at ? " · revisado pela equipe" : ""}{m.excluded ? " · fora da avaliação" : ""}</small></div>
        <button type="button" className="bhInfoBtn" aria-expanded={open === m.id} aria-label="De onde veio e revisar"
          onClick={() => setOpen((cur) => (cur === m.id ? null : m.id))}><CircleAlert size={18} aria-hidden="true" /></button>
      </div>
      {open === m.id ? <MentionInfo m={m} canReview={meta.canReview && meta.reviewEnabled} onSaved={saved} onClose={() => setOpen(null)} /> : null}
    </li>)}</ul>
    {loading ? <p className="bhMuted" role="status">Carregando…</p> : null}
    {meta.hasMore && !loading ? <button type="button" className="studioLink" onClick={() => void load(meta.next)}>Ver mais</button> : null}
  </section>;
}
