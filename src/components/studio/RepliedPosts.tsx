import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { getRepliesByPost, type RepliedPost } from "../../app/engagement";

const WHO: Record<string, string> = { ia: "IA", equipe: "Equipe", gatilho: "Gatilho", revisao: "Revisão" };
const STATUS: Record<string, string> = { enviado: "publicada", simulado: "simulada (não publicada)", pendente: "enviando", falhou: "falhou" };
const when = (iso?: string) => (iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "");

/** Publicações em que a marca respondeu comentários: quem respondeu (IA, equipe, gatilho), o quê e o que ficou para revisão. */
export default function RepliedPosts() {
  const clientId = getActiveClientId();
  const [days, setDays] = useState(30);
  const [posts, setPosts] = useState<RepliedPost[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setPosts(null); setError(null);
    getRepliesByPost(days).then((r) => { if (alive && getActiveClientId() === clientId) setPosts(r.posts || []); })
      .catch((cause) => { if (alive) { setError(cause instanceof Error ? cause.message : "Não foi possível carregar."); setPosts([]); } });
    return () => { alive = false; };
  }, [days, clientId]);

  const total = (posts || []).reduce((n, p) => n + p.counts.ia + p.counts.equipe + p.counts.gatilho, 0);
  return <section className="repliedPosts" aria-label="Respondidos por post">
    <div className="studioTabs" role="tablist" aria-label="Período">
      {[7, 30, 90].map((d) => <button key={d} role="tab" aria-selected={days === d} className={days === d ? "is-active" : ""} onClick={() => setDays(d)}>{d} dias</button>)}
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {posts === null ? <p>Carregando…</p> : null}
    {posts && !posts.length ? <div className="studioEmpty"><p>Nenhuma resposta nos últimos {days} dias.</p></div> : null}
    {posts && posts.length ? <p className="libHint">{total} resposta(s) em {posts.length} publicação(ões) nos últimos {days} dias.</p> : null}
    <ul className="repliedList">{(posts || []).map((p) => <li key={p.media_id}>
      <button type="button" className="repliedHead" aria-expanded={open === p.media_id} onClick={() => setOpen(open === p.media_id ? null : p.media_id)}>
        {p.thumb ? <img src={p.thumb} alt="" loading="lazy" /> : <span className="repliedNoThumb" aria-hidden="true">IG</span>}
        <span className="repliedInfo">
          <b>{p.caption || "Publicação"}</b>
          <small>{p.posted_at ? `Publicado ${when(p.posted_at)} · ` : ""}última resposta {when(p.last_at)}</small>
          <span className="repliedChips">
            {p.counts.ia ? <span className="studioChip">IA {p.counts.ia}</span> : null}
            {p.counts.equipe ? <span className="studioChip">Equipe {p.counts.equipe}</span> : null}
            {p.counts.gatilho ? <span className="studioChip">Gatilho {p.counts.gatilho}</span> : null}
            {p.counts.revisao ? <span className="studioChip is-warn">Revisão {p.counts.revisao}</span> : null}
            {p.counts.simulado ? <span className="studioChip">Simuladas {p.counts.simulado}</span> : null}
            {p.counts.falhou ? <span className="studioChip is-warn">Falhou {p.counts.falhou}</span> : null}
          </span>
        </span>
      </button>
      {open === p.media_id ? <div className="repliedBody">
        {p.permalink ? <a href={p.permalink} target="_blank" rel="noopener noreferrer">Abrir no Instagram ↗</a> : null}
        <ol>{p.replies.map((r, i) => <li key={i}>
          <p><b>@{r.username || "?"}</b>: {r.comment || "(comentário)"}</p>
          <p className="repliedAnswer"><small>{WHO[r.who]} · {STATUS[r.status]} · {when(r.at)}</small>{r.reply ? <span>{r.who === "revisao" ? `Motivo: ${r.reply}` : r.reply}</span> : null}</p>
        </li>)}</ol>
      </div> : null}
    </li>)}</ul>
  </section>;
}
