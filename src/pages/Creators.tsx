import { useCallback, useEffect, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  CREATOR_NETWORKS, CREATOR_SOURCES, ITEM_STATUS, addToShortlist, compareCreators, createShortlist, creatorCompact, creatorNumber,
  getCreatorUsage, getShortlist, listCreators, listShortlists, lookupCreator, refreshCreator, removeFromShortlist,
  searchCreators, suggestCreators, updateShortlistItem,
  type Creator, type CreatorNetwork, type CreatorSuggestion, type CreatorUsage, type ItemStatus, type Shortlist, type ShortlistItem,
} from "../app/creators";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import SegmentedControl from "../components/data/SegmentedControl";
import "../styles/creators.css";

const MAX_COMPARE = 5;
const MISSING_LABEL: Record<string, string> = {
  followers: "seguidores", avg_likes: "curtidas", avg_comments: "comentários", avg_views: "visualizações", engagement_rate: "engajamento",
};
const NETWORK_OPTIONS = Object.entries(CREATOR_NETWORKS).map(([id, label]) => ({ id, label }));
// TikTok e descoberta usam créditos Apify da Mugô: só a agência.
const CLIENT_NETWORK_OPTIONS = NETWORK_OPTIONS.filter((o) => o.id !== "tiktok");
const CAMPAIGN_OPTIONS = [{ id: "influencer", label: "Influência" }, { id: "ugc", label: "UGC" }];
type Busy = null | "lookup" | "search" | "suggest" | "other";
type SuggestResult = { suggestions: CreatorSuggestion[]; discarded: string[]; context_available: boolean };

function message(cause: unknown, fallback: string) {
  return cause instanceof Error ? cause.message : fallback;
}

function Avatar({ creator }: { creator: Creator }) {
  const [broken, setBroken] = useState(false);
  return creator.avatar_url && !broken
    ? <img className="creatorAvatar" src={creator.avatar_url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
    : <span className="creatorAvatar is-fallback" aria-hidden="true">{creator.handle.slice(0, 1).toUpperCase()}</span>;
}

function Engagement({ value }: { value: number | null }) {
  if (value == null) return <span className="creatorEng is-none">—</span>;
  const tone = value >= 3 ? "is-high" : value >= 1 ? "is-mid" : "is-low";
  return <span className={`creatorEng ${tone}`}>{creatorNumber(value, "%")}</span>;
}

function Identity({ creator }: { creator: Creator }) {
  return <div className="creatorIdentity">
    <Avatar creator={creator} />
    <div>
      <a href={creator.profile_url || undefined} target="_blank" rel="noreferrer">@{creator.handle}</a>
      <small>{creator.display_name || CREATOR_NETWORKS[creator.network]}</small>
    </div>
  </div>;
}

/**
 * isAgency: banco inteiro, descoberta paga e custos. Cliente vê só os criadores e shortlists da empresa.
 * canAct: agência ou client_admin analisam @, pedem sugestões e mexem nas shortlists; viewer só lê.
 */
export default function Creators({ isAgency = false, canAct = false }: { isAgency?: boolean; canAct?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName();
  const [network, setNetwork] = useState<CreatorNetwork>("instagram");
  const [handle, setHandle] = useState("");
  const [query, setQuery] = useState("");
  const [creators, setCreators] = useState<Creator[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Creator[] | null>(null);
  const [shortlists, setShortlists] = useState<Shortlist[]>([]);
  const [activeList, setActiveList] = useState("");
  const [listItems, setListItems] = useState<ShortlistItem[]>([]);
  const [newList, setNewList] = useState("");
  const [usage, setUsage] = useState<CreatorUsage | null>(null);
  const [aiType, setAiType] = useState<Shortlist["campaign_type"]>("influencer");
  const [aiBrief, setAiBrief] = useState("");
  const [aiResult, setAiResult] = useState<SuggestResult | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async (id: string) => {
    setListItems(id ? (await getShortlist(id)).items : []);
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([listCreators(), listShortlists(), getCreatorUsage()])
      .then(([catalog, lists, use]) => { if (!alive) return; setCreators(catalog.creators); setShortlists(lists.shortlists); setUsage(use); })
      .catch((cause) => { if (alive) setError(message(cause, "Não foi possível carregar os criadores.")); });
    return () => { alive = false; };
  }, [clientId]);

  async function run(kind: Exclude<Busy, null>, task: () => Promise<void>, fallback: string) {
    if (busy || getActiveClientId() !== clientId) return;
    setBusy(kind); setError(null);
    try { await task(); getCreatorUsage().then(setUsage).catch(() => undefined); }
    catch (cause) { setError(message(cause, fallback)); }
    finally { setBusy(null); }
  }

  const upsertLocal = (items: Creator[]) =>
    setCreators((current) => [...items, ...current.filter((c) => !items.some((i) => i.id === c.id))]);

  const addTo = (creatorId: string) =>
    run("other", async () => { await addToShortlist(activeList, creatorId); await loadList(activeList); }, "Não foi possível adicionar.");

  const toggle = (id: string) => setSelected((current) =>
    current.includes(id) ? current.filter((i) => i !== id) : current.length >= MAX_COMPARE ? current : [...current, id]);

  function onLookup(event: FormEvent) {
    event.preventDefault();
    if (!handle.trim()) return;
    run("lookup", async () => { upsertLocal([await lookupCreator(network, handle)]); setNotes([]); setHandle(""); }, "Não foi possível consultar o perfil.");
  }

  function onSearch(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    run("search", async () => { const result = await searchCreators(network, query); upsertLocal(result.creators); setNotes(result.notes); }, "Não foi possível pesquisar.");
  }

  function onSuggest(event: FormEvent) {
    event.preventDefault();
    run("suggest", async () => {
      const result = await suggestCreators(aiType, aiBrief);
      setAiResult(result); upsertLocal(result.suggestions.map((s) => s.creator));
    }, "Não foi possível gerar sugestões.");
  }

  const progress = busy === "suggest" ? "A IA está escolhendo perfis e conferindo cada um na Meta. Leva até 1 minuto…"
    : busy === "search" ? "Pesquisando criadores. Execuções na Apify podem levar até 2 minutos…"
      : busy === "lookup" ? "Consultando o perfil…" : busy ? "Salvando…" : null;
  const activeListName = shortlists.find((s) => s.id === activeList)?.name;

  return <Shell title="Criadores" variant="editorial"><div className="ds-page creatorsPage">
    <div className="creatorIntro">
      <PageHeader company={clientName} title="Criadores" />
      <p>Descubra, analise e selecione criadores UGC e influenciadores. Métricas públicas com fonte e data; campos ausentes são sinalizados, nunca estimados.</p>
      {usage && isAgency ? <ul className="creatorChips" aria-label="Consumo das fontes">
        {usage.apify ? <li className={usage.apify.blocked ? "is-warning" : ""}>Apify US$ {usage.apify.month_spent_usd.toFixed(2)} / {usage.apify.month_budget_usd.toFixed(2)} no mês</li> : null}
        {usage.youtube ? <li>YouTube {usage.youtube.today_units.toLocaleString("pt-BR")} / {usage.youtube.daily_units_limit.toLocaleString("pt-BR")} unidades hoje</li> : null}
        <li>Meta: {usage.meta.month_calls_this_client} consultas no mês · grátis</li>
      </ul> : null}
    </div>

    <div className="creatorWork">
      {canAct ? <div className="creatorPanels">
        <section className="creatorCard" aria-labelledby="creator-find">
          <header><h2 id="creator-find">Encontrar criadores</h2>
            <SegmentedControl ariaLabel="Rede" options={isAgency ? NETWORK_OPTIONS : CLIENT_NETWORK_OPTIONS} value={network} onSelect={(id) => setNetwork(id as CreatorNetwork)} /></header>
          <form onSubmit={onLookup} className="creatorRow">
            <label className="ds-field">Analisar perfil
              <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@criador ou link do perfil" /></label>
            <button className="ds-button is-primary" disabled={Boolean(busy)}>Analisar</button>
          </form>
          {isAgency ? <form onSubmit={onSearch} className="creatorRow">
            <label className="ds-field">Descobrir por {network === "youtube" ? "palavra-chave" : "hashtag"}
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={network === "youtube" ? "vinhos, harmonização" : "#vinhonacional"} /></label>
            <button className="ds-button" disabled={Boolean(busy)}>Descobrir</button>
          </form> : null}
          <small>{!isAgency ? "Analise o @ de um criador do Instagram ou do YouTube para ver as métricas oficiais."
            : network === "instagram" ? "Analisar um @ usa a Meta, sem custo. Descobrir por hashtag usa créditos Apify (teto mensal)."
            : network === "youtube" ? "YouTube oficial: analisar custa 3 unidades e buscar, 101, da cota diária grátis."
              : "TikTok usa créditos Apify (teto mensal)."}</small>
        </section>

        <section className="creatorCard is-ai" aria-labelledby="creator-ai">
          <header><h2 id="creator-ai">Sugerir com IA para {clientName}</h2>
            <SegmentedControl ariaLabel="Tipo de campanha" options={CAMPAIGN_OPTIONS} value={aiType} onSelect={(id) => setAiType(id as Shortlist["campaign_type"])} /></header>
          <form onSubmit={onSuggest} className="creatorAiForm">
            <label className="ds-field">Briefing (opcional)
              <textarea value={aiBrief} maxLength={1000} rows={3} onChange={(e) => setAiBrief(e.target.value)} placeholder="ex.: Black Friday para girar o estoque de tintos, público 30-55" /></label>
            <button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "suggest" ? "Gerando…" : "Sugerir @ do Instagram"}</button>
          </form>
          <small>A IA usa o contexto de negócio da empresa. Cada @ é conferido na Meta: só aparecem contas reais e profissionais, com métricas oficiais.</small>
        </section>
      </div> : null}

      {progress ? <p className="creatorProgress" role="status"><span className="creatorSpinner" aria-hidden="true" />{progress}</p> : null}
      {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
      {notes.length ? <div className="ds-notice is-warning">{notes.map((note) => <p key={note}>{note}</p>)}</div> : null}

      {aiResult ? <section className="creatorCard" aria-labelledby="creator-ai-result">
        <header><h2 id="creator-ai-result">Sugestões da IA · {aiResult.suggestions.length}</h2>
          <button type="button" className="ds-button" onClick={() => setAiResult(null)}>Fechar</button></header>
        {!aiResult.context_available ? <p className="creatorMuted">O contexto de negócio desta empresa não está preenchido (Empresas → editar), por isso as sugestões ficam mais genéricas.</p> : null}
        {!aiResult.suggestions.length ? <p>Nenhuma indicação foi confirmada na Meta. Detalhe o briefing e tente de novo.</p> :
          <div className="creatorSuggestGrid">{aiResult.suggestions.map(({ creator, reason }) => <article key={creator.id} className="creatorSuggest">
            <Identity creator={creator} />
            <dl><div><dt>Seguidores</dt><dd>{creatorCompact(creator.followers)}</dd></div><div><dt>Engajamento</dt><dd><Engagement value={creator.engagement_rate} /></dd></div></dl>
            <p>{reason}</p>
            {!canAct ? null : activeList ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => addTo(creator.id)}>+ {activeListName}</button>
              : <small className="creatorMuted">Escolha uma shortlist para adicionar.</small>}
          </article>)}</div>}
        {aiResult.discarded.length ? <p className="creatorMuted">Descartados (não encontrados ou não profissionais na Meta): {aiResult.discarded.map((h) => `@${h}`).join(", ")}</p> : null}
      </section> : null}

      <div className="creatorToolbar">
        <button type="button" className="ds-button" disabled={selected.length < 2 || Boolean(busy)}
          onClick={() => run("other", async () => setComparison((await compareCreators(selected)).creators), "Não foi possível comparar.")}>
          Comparar {selected.length ? `(${selected.length}/${MAX_COMPARE})` : ""}
        </button>
        <select value={activeList} aria-label="Shortlist ativa" onChange={(e) => { setActiveList(e.target.value); run("other", () => loadList(e.target.value), "Não foi possível abrir a shortlist."); }}>
          <option value="">Shortlist ativa…</option>
          {shortlists.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.campaign_type === "ugc" ? "UGC" : "Influência"})</option>)}
        </select>
        {canAct ? <form onSubmit={(e) => { e.preventDefault(); if (!newList.trim()) return; run("other", async () => { const created = await createShortlist(newList, aiType); setShortlists((c) => [created, ...c]); setActiveList(created.id); setListItems([]); setNewList(""); }, "Não foi possível criar a shortlist."); }}>
          <input value={newList} onChange={(e) => setNewList(e.target.value)} placeholder="Nova shortlist" aria-label="Nome da nova shortlist" />
          <button className="ds-button" disabled={Boolean(busy)}>Criar</button>
        </form> : null}
      </div>

      {comparison ? <section className="creatorCard" aria-labelledby="creator-compare">
        <header><h2 id="creator-compare">Comparador</h2><button type="button" className="ds-button" onClick={() => setComparison(null)}>Fechar</button></header>
        <div className="creatorScroll"><table className="ds-table"><thead><tr><th>Indicador</th>{comparison.map((c) => <th key={c.id}>@{c.handle}</th>)}</tr></thead><tbody>
          {([["Rede", (c: Creator) => CREATOR_NETWORKS[c.network]], ["Seguidores", (c: Creator) => creatorNumber(c.followers)],
            ["Média de curtidas", (c: Creator) => creatorNumber(c.avg_likes == null ? null : Math.round(c.avg_likes))],
            ["Média de comentários", (c: Creator) => creatorNumber(c.avg_comments == null ? null : Math.round(c.avg_comments))],
            ["Média de visualizações", (c: Creator) => creatorNumber(c.avg_views == null ? null : Math.round(c.avg_views))],
            ["Engajamento", (c: Creator) => <Engagement value={c.engagement_rate} />],
            ["Amostra", (c: Creator) => `${c.sample_size} posts`], ["Fonte", (c: Creator) => CREATOR_SOURCES[c.source] || c.source],
            ["Coleta", (c: Creator) => new Date(c.collected_at).toLocaleDateString("pt-BR")]] as const)
            .map(([label, value]) => <tr key={label}><th>{label}</th>{comparison.map((c) => <td key={c.id}>{value(c)}</td>)}</tr>)}
        </tbody></table></div>
      </section> : null}

      {activeList ? <section className="creatorCard" aria-labelledby="creator-list">
        <header><h2 id="creator-list">{activeListName} · {listItems.length}</h2></header>
        {!listItems.length ? <p className="creatorMuted">Nenhum criador nesta shortlist. Use “+ Shortlist” na tabela ou nas sugestões.</p> :
          <ul className="creatorListItems">{listItems.map((item) => <li key={item.id}>
            {item.creators ? <Identity creator={item.creators} /> : null}
            <span>{creatorCompact(item.creators?.followers)} seguidores</span>
            <Engagement value={item.creators?.engagement_rate ?? null} />
            {canAct ? <><select value={item.status} aria-label="Status" onChange={(e) => run("other", async () => { await updateShortlistItem(activeList, item.id, e.target.value as ItemStatus); await loadList(activeList); }, "Não foi possível atualizar.")}>
              {Object.entries(ITEM_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <button type="button" className="ds-button" onClick={() => run("other", async () => { await removeFromShortlist(activeList, item.id); await loadList(activeList); }, "Não foi possível remover.")}>Remover</button></> : <span className="creatorMuted">{ITEM_STATUS[item.status]}</span>}
          </li>)}</ul>}
      </section> : null}

      <section className="creatorCard" aria-labelledby="creator-bank">
        <header><h2 id="creator-bank">Banco de criadores · {creators.length}</h2></header>
        {!creators.length ? <p className="creatorMuted">{isAgency ? "Nenhum criador no banco ainda. Analise um @, descubra por hashtag ou peça sugestões à IA."
          : canAct ? "Nenhum criador da sua empresa ainda. Analise um @ ou peça sugestões à IA." : "A Mugô ainda não selecionou criadores para a sua empresa."}</p> :
          <div className="creatorScroll"><table className="ds-table creatorTable">
            <thead><tr><th aria-label="Comparar" /><th>Criador</th><th className="is-number">Seguidores</th><th className="is-number">Curtidas</th><th className="is-number">Comentários</th><th className="is-number">Engajamento</th><th>Dados</th><th aria-label="Ações" /></tr></thead>
            <tbody>{creators.map((creator) => <tr key={creator.id}>
              <td><input type="checkbox" checked={selected.includes(creator.id)} onChange={() => toggle(creator.id)} aria-label={`Comparar @${creator.handle}`} /></td>
              <td><Identity creator={creator} /></td>
              <td className="is-number" title={creatorNumber(creator.followers)}>{creatorCompact(creator.followers)}</td>
              <td className="is-number" title="Média dos posts recentes">{creatorCompact(creator.avg_likes)}</td>
              <td className="is-number" title="Média dos posts recentes">{creatorCompact(creator.avg_comments)}</td>
              <td className="is-number" title={creator.engagement_method || undefined}><Engagement value={creator.engagement_rate} /></td>
              <td>
                <small>{CREATOR_SOURCES[creator.source] || creator.source} · {new Date(creator.collected_at).toLocaleDateString("pt-BR")} · {creator.sample_size} posts</small>
                {creator.missing_fields?.length ? <small className="creatorMissing">Sem {creator.missing_fields.map((f) => MISSING_LABEL[f] || f).join(", ")}</small> : null}
              </td>
              <td>{canAct ? <div className="creatorActions">
                <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => run("other", async () => upsertLocal([await refreshCreator(creator.id)]), "Não foi possível atualizar o perfil.")}>Atualizar</button>
                {activeList ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => addTo(creator.id)}>+ Shortlist</button> : null}
              </div> : null}</td>
            </tr>)}</tbody>
          </table></div>}
      </section>
    </div>
  </div></Shell>;
}
