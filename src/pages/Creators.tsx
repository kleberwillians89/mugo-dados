import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  CREATOR_NETWORKS, CREATOR_SOURCES, ITEM_STATUS, addToShortlist, compareCreators, createShortlist, creatorNumber,
  getCreatorUsage, getShortlist, listCreators, listShortlists, lookupCreator, refreshCreator, removeFromShortlist,
  searchCreators, suggestCreators, updateShortlistItem,
  type Creator, type CreatorSuggestion, type CreatorNetwork, type CreatorUsage, type ItemStatus, type Shortlist, type ShortlistItem,
} from "../app/creators";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/creators.css";

const MAX_COMPARE = 5;
const MISSING_LABEL: Record<string, string> = {
  followers: "seguidores", avg_likes: "curtidas", avg_comments: "comentários", avg_views: "visualizações", engagement_rate: "engajamento",
};

function message(cause: unknown, fallback: string) {
  return cause instanceof Error ? cause.message : fallback;
}

function CreatorRow({ creator, selected, onSelect, onRefresh, onAdd, canAdd }: {
  creator: Creator; selected: boolean; onSelect: () => void; onRefresh: () => void; onAdd: () => void; canAdd: boolean;
}) {
  return <tr>
    <td><input type="checkbox" checked={selected} onChange={onSelect} aria-label={`Comparar @${creator.handle}`} /></td>
    <td>
      <a href={creator.profile_url || undefined} target="_blank" rel="noreferrer"><strong>@{creator.handle}</strong></a>
      <small>{creator.display_name || ""} · {CREATOR_NETWORKS[creator.network]}</small>
    </td>
    <td>{creatorNumber(creator.followers)}</td>
    <td>{creatorNumber(creator.avg_likes)}</td>
    <td>{creatorNumber(creator.avg_comments)}</td>
    <td title={creator.engagement_method || undefined}>{creatorNumber(creator.engagement_rate, "%")}</td>
    <td>
      <small>{CREATOR_SOURCES[creator.source] || creator.source}</small>
      <small>{new Date(creator.collected_at).toLocaleDateString("pt-BR")} · {creator.sample_size} posts</small>
      {creator.missing_fields?.length ? <small className="creatorMissing">Sem {creator.missing_fields.map((f) => MISSING_LABEL[f] || f).join(", ")}</small> : null}
    </td>
    <td className="creatorActions">
      <button type="button" className="ds-button ds-button--ghost" onClick={onRefresh}>Atualizar</button>
      {canAdd ? <button type="button" className="ds-button ds-button--ghost" onClick={onAdd}>+ Shortlist</button> : null}
    </td>
  </tr>;
}

export default function Creators() {
  const clientId = getActiveClientId();
  const [network, setNetwork] = useState<CreatorNetwork>("instagram");
  const [handle, setHandle] = useState("");
  const [query, setQuery] = useState("");
  const [creators, setCreators] = useState<Creator[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Creator[] | null>(null);
  const [shortlists, setShortlists] = useState<Shortlist[]>([]);
  const [activeList, setActiveList] = useState<string>("");
  const [listItems, setListItems] = useState<ShortlistItem[]>([]);
  const [newList, setNewList] = useState("");
  const [usage, setUsage] = useState<CreatorUsage | null>(null);
  const [aiType, setAiType] = useState<Shortlist["campaign_type"]>("influencer");
  const [aiBrief, setAiBrief] = useState("");
  const [aiResult, setAiResult] = useState<{ suggestions: CreatorSuggestion[]; discarded: string[]; context_available: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async (id: string) => {
    if (!id) { setListItems([]); return; }
    setListItems((await getShortlist(id)).items);
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([listCreators(), listShortlists(), getCreatorUsage()])
      .then(([catalog, lists, use]) => { if (!alive) return; setCreators(catalog.creators); setShortlists(lists.shortlists); setUsage(use); })
      .catch((cause) => { if (alive) setError(message(cause, "Não foi possível carregar os criadores.")); });
    return () => { alive = false; };
  }, [clientId]);

  async function run(task: () => Promise<void>, fallback: string) {
    if (busy || getActiveClientId() !== clientId) return;
    setBusy(true); setError(null);
    try { await task(); getCreatorUsage().then(setUsage).catch(() => undefined); }
    catch (cause) { setError(message(cause, fallback)); }
    finally { setBusy(false); }
  }

  const upsertLocal = (items: Creator[]) =>
    setCreators((current) => [...items, ...current.filter((c) => !items.some((i) => i.id === c.id))]);

  function onLookup(event: FormEvent) {
    event.preventDefault();
    if (!handle.trim()) return;
    run(async () => { upsertLocal([await lookupCreator(network, handle)]); setNotes([]); setHandle(""); }, "Não foi possível consultar o perfil.");
  }

  function onSearch(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    run(async () => { const result = await searchCreators(network, query); upsertLocal(result.creators); setNotes(result.notes); }, "Não foi possível pesquisar.");
  }

  function onSuggest(event: FormEvent) {
    event.preventDefault();
    run(async () => { const result = await suggestCreators(aiType, aiBrief); setAiResult(result); upsertLocal(result.suggestions.map((s) => s.creator)); }, "Não foi possível gerar sugestões.");
  }

  const toggle = (id: string) => setSelected((current) =>
    current.includes(id) ? current.filter((i) => i !== id) : current.length >= MAX_COMPARE ? current : [...current, id]);

  return <Shell title="Criadores" variant="editorial"><div className="ds-page creatorsPage">
    <PageHeader company={getActiveClientName()} title="Criadores" />
    <p>Descubra, analise e selecione criadores UGC e influenciadores. Métricas públicas com fonte e data; campos ausentes são sinalizados, nunca estimados.</p>

    {usage ? <p className="creatorUsage">
      Apify no mês: US$ {usage.apify.month_spent_usd.toFixed(2)} de US$ {usage.apify.month_budget_usd.toFixed(2)}{usage.apify.blocked ? " (bloqueado)" : ""}
      {" · "}YouTube hoje: {usage.youtube.today_units} de {usage.youtube.daily_units_limit} unidades
      {" · "}Consultas Meta desta empresa no mês: {usage.meta.month_calls_this_client}
    </p> : null}

    <div className="creatorTools">
      <label>Rede
        <select value={network} onChange={(e) => setNetwork(e.target.value as CreatorNetwork)}>
          {Object.entries(CREATOR_NETWORKS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <form onSubmit={onLookup}>
        <label>Analisar perfil <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@criador ou link" /></label>
        <button className="ds-button" disabled={busy}>Analisar</button>
      </form>
      <form onSubmit={onSearch}>
        <label>Descobrir por {network === "youtube" ? "palavra-chave" : "hashtag"} <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={network === "youtube" ? "perfume nicho" : "#perfumenacional"} /></label>
        <button className="ds-button" disabled={busy}>Descobrir</button>
      </form>
    </div>
    {network !== "youtube" ? <small>Descoberta no {CREATOR_NETWORKS[network]} usa créditos Apify (com teto mensal). Analisar um @ do Instagram usa a Meta, sem custo.</small> : <small>Busca no YouTube consome 101 unidades da cota diária gratuita.</small>}

    <form className="creatorAi" onSubmit={onSuggest}>
      <strong>Sugerir com IA para {getActiveClientName()}</strong>
      <label>Campanha
        <select value={aiType} onChange={(e) => setAiType(e.target.value as Shortlist["campaign_type"])}>
          <option value="influencer">Influência</option><option value="ugc">UGC</option>
        </select>
      </label>
      <label>Briefing (opcional) <input value={aiBrief} maxLength={1000} onChange={(e) => setAiBrief(e.target.value)} placeholder="ex.: lançamento de perfume amadeirado, público 25-40" /></label>
      <button className="ds-button" disabled={busy}>Sugerir @</button>
      <small>A IA indica perfis do Instagram com base no contexto de negócio da empresa; cada @ é conferido na Meta e só aparecem contas reais e profissionais, com métricas oficiais.</small>
    </form>
    {aiResult ? <section className="creatorShortlist">
      <h2>Sugestões da IA <button type="button" className="ds-button ds-button--ghost" onClick={() => setAiResult(null)}>Fechar</button></h2>
      {!aiResult.context_available ? <p className="creatorNote">Contexto de negócio desta empresa não preenchido (Empresas → editar): as sugestões ficam mais genéricas.</p> : null}
      {!aiResult.suggestions.length ? <p>Nenhuma indicação foi confirmada na Meta. Tente detalhar o briefing.</p> : <ul>{aiResult.suggestions.map(({ creator, reason }) => <li key={creator.id}>
        <a href={creator.profile_url || undefined} target="_blank" rel="noreferrer"><strong>@{creator.handle}</strong></a>
        · {creatorNumber(creator.followers)} seguidores · {creatorNumber(creator.engagement_rate, "%")} · <span>{reason}</span>
        {activeList ? <button type="button" className="ds-button ds-button--ghost" onClick={() => run(async () => { await addToShortlist(activeList, creator.id); await loadList(activeList); }, "Não foi possível adicionar.")}>+ Shortlist</button> : null}
      </li>)}</ul>}
      {aiResult.discarded.length ? <p className="creatorNote">Descartados (não encontrados ou não profissionais na Meta): {aiResult.discarded.map((h) => `@${h}`).join(", ")}</p> : null}
    </section> : null}

    {error ? <p role="alert">{error}</p> : null}
    {busy ? <p>Consultando…</p> : null}
    {notes.map((note) => <p key={note} className="creatorNote">{note}</p>)}

    <div className="creatorBar">
      <button type="button" className="ds-button" disabled={selected.length < 2 || busy}
        onClick={() => run(async () => setComparison((await compareCreators(selected)).creators), "Não foi possível comparar.")}>
        Comparar ({selected.length}/{MAX_COMPARE})
      </button>
      <select value={activeList} onChange={(e) => { setActiveList(e.target.value); run(() => loadList(e.target.value), "Não foi possível abrir a shortlist."); }}>
        <option value="">Shortlist ativa…</option>
        {shortlists.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.campaign_type === "ugc" ? "UGC" : "Influência"})</option>)}
      </select>
      <form onSubmit={(e) => { e.preventDefault(); if (!newList.trim()) return; run(async () => { const created = await createShortlist(newList, "influencer"); setShortlists((c) => [created, ...c]); setActiveList(created.id); setListItems([]); setNewList(""); }, "Não foi possível criar a shortlist."); }}>
        <input value={newList} onChange={(e) => setNewList(e.target.value)} placeholder="Nova shortlist" aria-label="Nome da nova shortlist" />
        <button className="ds-button ds-button--ghost" disabled={busy}>Criar</button>
      </form>
    </div>

    {comparison ? <section className="creatorCompare">
      <h2>Comparador <button type="button" className="ds-button ds-button--ghost" onClick={() => setComparison(null)}>Fechar</button></h2>
      <table><thead><tr><th>Indicador</th>{comparison.map((c) => <th key={c.id}>@{c.handle}</th>)}</tr></thead><tbody>
        {([["Rede", (c: Creator) => CREATOR_NETWORKS[c.network]], ["Seguidores", (c: Creator) => creatorNumber(c.followers)],
          ["Média de curtidas", (c: Creator) => creatorNumber(c.avg_likes)], ["Média de comentários", (c: Creator) => creatorNumber(c.avg_comments)],
          ["Média de visualizações", (c: Creator) => creatorNumber(c.avg_views)], ["Engajamento", (c: Creator) => creatorNumber(c.engagement_rate, "%")],
          ["Amostra", (c: Creator) => `${c.sample_size} posts`], ["Fonte", (c: Creator) => CREATOR_SOURCES[c.source] || c.source],
          ["Coleta", (c: Creator) => new Date(c.collected_at).toLocaleDateString("pt-BR")]] as const)
          .map(([label, value]) => <tr key={label}><th>{label}</th>{comparison.map((c) => <td key={c.id}>{value(c)}</td>)}</tr>)}
      </tbody></table>
    </section> : null}

    {activeList ? <section className="creatorShortlist">
      <h2>{shortlists.find((s) => s.id === activeList)?.name}</h2>
      {!listItems.length ? <p>Nenhum criador nesta shortlist.</p> : <ul>{listItems.map((item) => <li key={item.id}>
        <strong>@{item.creators?.handle}</strong> · {creatorNumber(item.creators?.followers)} seguidores · {creatorNumber(item.creators?.engagement_rate, "%")}
        <select value={item.status} onChange={(e) => run(async () => { await updateShortlistItem(activeList, item.id, e.target.value as ItemStatus); await loadList(activeList); }, "Não foi possível atualizar.")}>
          {Object.entries(ITEM_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <button type="button" className="ds-button ds-button--ghost" onClick={() => run(async () => { await removeFromShortlist(activeList, item.id); await loadList(activeList); }, "Não foi possível remover.")}>Remover</button>
      </li>)}</ul>}
    </section> : null}

    <div className="creatorTableWrap"><table className="creatorTable">
      <thead><tr><th /><th>Criador</th><th>Seguidores</th><th>Curtidas (média)</th><th>Comentários (média)</th><th>Engajamento</th><th>Dados</th><th /></tr></thead>
      <tbody>
        {creators.map((creator) => <CreatorRow key={creator.id} creator={creator} selected={selected.includes(creator.id)} onSelect={() => toggle(creator.id)}
          canAdd={Boolean(activeList)}
          onRefresh={() => run(async () => upsertLocal([await refreshCreator(creator.id)]), "Não foi possível atualizar o perfil.")}
          onAdd={() => run(async () => { await addToShortlist(activeList, creator.id); await loadList(activeList); }, "Não foi possível adicionar.")} />)}
      </tbody>
    </table></div>
    {!creators.length && !busy ? <p>Nenhum criador no banco ainda. Analise um @ ou descubra por hashtag.</p> : null}
  </div></Shell>;
}
