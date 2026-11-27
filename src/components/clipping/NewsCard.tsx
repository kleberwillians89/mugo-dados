import { useState, type ReactNode } from "react";
import { KIND_LABEL, SENTIMENT_LABEL, type Clipping } from "../../app/contentOps";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }) : "");
const TONE: Record<string, string> = { positivo: "ok", negativo: "bad", misto: "warn", neutro: "neu" };

/**
 * Notícia em card, como num portal: capa da matéria (ou o ícone e o nome do veículo), selos, título, resumo e ações.
 * Link do Google Notícias não traz capa: o card mostra o veículo em destaque, com a cor do tipo (marca, concorrente…).
 */
export default function NewsCard({ item, actions, compact = false }: { item: Clipping; actions?: ReactNode; compact?: boolean }) {
  const [broken, setBroken] = useState(false);
  const image = item.image_url && !broken ? item.image_url : null;
  const source = item.source || item.source_domain || "Fonte";
  return <article className={`newsCard is-${item.kind}${item.status === "lido" ? " is-read" : ""}${item.relevant === false ? " is-irrelevant" : ""}${compact ? " is-compact" : ""}`}>
    <a className="newsMedia" href={item.url} target="_blank" rel="noreferrer noopener" tabIndex={-1} aria-hidden="true">
      {image ? <img src={image} alt="" loading="lazy" onError={() => setBroken(true)} referrerPolicy="no-referrer" />
        : <span className="newsSourceTile">
          {item.source_domain ? <img src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(item.source_domain)}&sz=64`} alt="" loading="lazy" referrerPolicy="no-referrer" /> : null}
          <b>{source}</b>
        </span>}
      <span className={`newsKind is-${item.kind}`}>{KIND_LABEL[item.kind] || item.kind}{item.term ? ` · ${item.term}` : ""}</span>
    </a>
    <div className="newsBody">
      <div className="newsChips">
        <span className={`mlChip is-${TONE[item.sentiment || ""] || "neu"}`}>{item.sentiment ? SENTIMENT_LABEL[item.sentiment] : "Sem leitura"}</span>
        {item.relevance != null ? <span className="mlChip is-neu">Relevância {item.relevance}</span> : null}
        {item.status === "novo" ? <span className="newsNew">Nova</span> : null}
      </div>
      <h4><a href={item.url} target="_blank" rel="noreferrer noopener">{item.title}</a></h4>
      <small className="newsMeta">{source} · {when(item.published_at || item.created_at)}</small>
      {item.summary && !compact ? <p>{item.summary}</p> : null}
      {item.relevant === false ? <p className="clipWarn">A IA acha que não é sobre a marca (homônimo ou citação de passagem).</p> : null}
      {actions ? <div className="newsActions">{actions}</div> : null}
    </div>
  </article>;
}
