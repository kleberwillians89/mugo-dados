import { useEffect, useState } from "react";
import { importMetaCampaign, readMetaCampaigns, type AdDraft, type MetaAccountCampaign } from "../../app/metaAds";

const STATUS: Record<string, string> = { ACTIVE: "Ativa", PAUSED: "Pausada", CAMPAIGN_PAUSED: "Pausada", IN_PROCESS: "Em processamento",
  WITH_ISSUES: "Com problema", PENDING_REVIEW: "Em análise", DISAPPROVED: "Recusada" };
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

/** Lista as campanhas da conta da Meta e traz a escolhida para a Mídia On (status, ligar/pausar, pixel e resultados). */
export default function MetaImportCampaign({ onImported, onClose }: { onImported: (draft: AdDraft) => void; onClose: () => void }) {
  const [list, setList] = useState<MetaAccountCampaign[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    readMetaCampaigns().then((r) => { if (alive) setList(r.campaigns); })
      .catch((cause) => { if (alive) setError(message(cause, "Não consegui ler as campanhas da Meta.")); });
    return () => { alive = false; };
  }, []);

  async function bring(c: MetaAccountCampaign) {
    setBusy(c.id); setError(null);
    try {
      const { draft } = await importMetaCampaign(c.id);
      setList((all) => all && all.map((x) => (x.id === c.id ? { ...x, imported: true } : x)));
      onImported(draft);
    } catch (cause) { setError(message(cause, "Não foi possível trazer esta campanha.")); }
    finally { setBusy(null); }
  }

  const shown = (list || []).filter((c) => !query.trim() || c.name.toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="metaImport" aria-label="Puxar campanha da Meta">
    <div className="metaImportHead">
      <div><b>Puxar campanha que já está na Meta</b>
        <small>Ela aparece aqui com o status real, Ativar/Pausar, pixel e resultados. Nada muda na Meta ao puxar.</small></div>
      <button type="button" className="ds-button" onClick={onClose}>Fechar</button>
    </div>
    <input className="metaImportSearch" type="search" placeholder="Buscar pelo nome" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar campanha" />
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {!list && !error ? <p className="ds-caption">Lendo as campanhas da conta…</p> : null}
    {list && !shown.length ? <p className="ds-caption">Nenhuma campanha encontrada.</p> : null}
    <ul className="metaImportList">{shown.map((c) => <li key={c.id}>
      <div><b>{c.name}</b>
        <small>{STATUS[c.status] || c.status}{c.daily_budget ? ` · ${c.daily_budget.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}/dia` : ""}{c.created_time ? ` · criada em ${new Date(c.created_time).toLocaleDateString("pt-BR")}` : ""}</small></div>
      {c.imported ? <span className="metaImportDone">Já na Mídia On</span>
        : <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void bring(c)}>{busy === c.id ? "Trazendo…" : "Trazer"}</button>}
    </li>)}</ul>
  </section>;
}
