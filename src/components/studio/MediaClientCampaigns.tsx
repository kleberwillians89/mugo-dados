import { useEffect, useMemo, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../../app/activeClient";
import { readMetaCampaignOverview, type MetaOverviewCampaign } from "../../app/metaAds";
import "./MediaClientCampaigns.css";

type CampaignRow = MetaOverviewCampaign;
export type CampaignFilter = "all" | "active" | "paused" | "finished" | "review" | "issues" | "other";

export function campaignCategory(c: Pick<MetaOverviewCampaign, "status" | "stop_time">, now = Date.now()): Exclude<CampaignFilter, "all"> {
  const status = String(c.status || "").toUpperCase();
  // A data de término prevalece sobre o status de veiculação retornado pela Meta.
  if (status === "ARCHIVED" || status === "DELETED" ||
      (c.stop_time && Number.isFinite(Date.parse(c.stop_time)) && Date.parse(c.stop_time) <= now)) return "finished";
  if (status === "ACTIVE") return "active";
  if (status === "PAUSED" || status === "CAMPAIGN_PAUSED" || status === "ADSET_PAUSED") return "paused";
  if (status === "PENDING_REVIEW" || status === "IN_PROCESS") return "review";
  if (status === "WITH_ISSUES" || status === "DISAPPROVED") return "issues";
  return "other";
}

const FILTERS: { value: CampaignFilter; label: string }[] = [
  { value: "all", label: "Todos os status" },
  { value: "active", label: "Ativas" },
  { value: "paused", label: "Pausadas" },
  { value: "finished", label: "Encerradas / arquivadas" },
  { value: "review", label: "Em análise" },
  { value: "issues", label: "Com problemas" },
  { value: "other", label: "Outros" },
];
const labelFor = (state: CampaignFilter) => ({
  all: "Todos", active: "Ativa", paused: "Pausada", finished: "Encerrada",
  review: "Em análise", issues: "Com problemas", other: "Outro estado",
})[state];
const money = (value: number | null) => value == null ? "—" : value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export default function MediaClientCampaigns() {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName();
  const [campaigns, setCampaigns] = useState<CampaignRow[]>([]);
  const [status, setStatus] = useState<CampaignFilter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(null); setCampaigns([]); setStatus("all"); setSearch("");
    if (!clientId) {
      setLoading(false);
      setError("Selecione uma empresa para visualizar suas campanhas.");
      return () => { active = false; };
    }
    readMetaCampaignOverview(clientId)
      .then((response) => {
        if (active && getActiveClientId() === clientId) setCampaigns(response.campaigns);
      })
      .catch(() => {
        if (active && getActiveClientId() === clientId)
          setError("Não foi possível consultar as campanhas Meta desta empresa. Confira a conexão.");
      })
      .finally(() => {
        if (active && getActiveClientId() === clientId) setLoading(false);
      });
    return () => { active = false; };
  }, [clientId, refreshKey]);

  const filtered = useMemo(() => campaigns.filter((campaign) => {
    if (status !== "all" && campaignCategory(campaign) !== status) return false;
    return !search.trim() || campaign.name.toLocaleLowerCase("pt-BR").includes(search.trim().toLocaleLowerCase("pt-BR"));
  }), [campaigns, status, search]);

  const counts = useMemo(() => FILTERS.reduce((acc, f) => {
    acc[f.value] = f.value === "all" ? campaigns.length : campaigns.filter((c) => campaignCategory(c) === f.value).length;
    return acc;
  }, {} as Record<CampaignFilter, number>), [campaigns]);

  return <section className="mediaAllClients" aria-labelledby="media-all-clients-heading">
    <div className="mediaAllClientsHeading">
      <div>
        <span className="mediaAllClientsEyebrow">MÍDIA ON / CAMPANHAS DA EMPRESA</span>
        <h2 id="media-all-clients-heading">Campanhas de {clientName}</h2>
        <p>Visualize e filtre campanhas desta empresa na Meta, sem alterar anúncios nem outras contas.</p>
      </div>
      <button className="ds-button" type="button" disabled={loading} onClick={() => setRefreshKey((k) => k + 1)}>Atualizar campanhas</button>
    </div>
    <div className="mediaAllClientsFilters">
      <label>Status
        <select aria-label="Filtrar por status" value={status} onChange={(e) => setStatus(e.target.value as CampaignFilter)}>
          {FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label} ({counts[f.value] || 0})</option>)}
        </select>
      </label>
      <label>Buscar campanha
        <input aria-label="Buscar campanha" placeholder="Nome da campanha" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
    </div>
    {loading ? <p role="status">Consultando as campanhas Meta desta empresa…</p> : null}
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {!loading && !error ? <>
      <p className="mediaAllClientsTotal" role="status">{filtered.length.toLocaleString("pt-BR")} campanha(s) encontrada(s) nesta empresa.</p>
      {filtered.length ? <div className="mediaAllClientsTableWrap">
        <table className="mediaAllClientsTable">
          <thead><tr><th>Campanha</th><th>Status</th><th>Objetivo Meta</th><th>Verba diária</th></tr></thead>
          <tbody>{filtered.map((c) => {
            const category = campaignCategory(c);
            return <tr key={c.id}>
              <td><strong>{c.name}</strong>{c.stop_time ? <small>Fim: {new Date(c.stop_time).toLocaleDateString("pt-BR")}</small> : null}</td>
              <td><span className={`mediaAllClientsState is-${category}`}>{labelFor(category)}</span></td>
              <td>{c.objective || "—"}</td><td>{money(c.daily_budget)}</td>
            </tr>;
          })}</tbody>
        </table>
      </div> : <p className="ds-noticeText">Nenhuma campanha corresponde aos filtros desta empresa. Confira sua conexão Meta ou tente outro status.</p>}
      <p className="ds-footnote">Status da conta Meta desta empresa. Encerradas incluem campanhas arquivadas e aquelas com data de término vencida. Consulta somente leitura.</p>
    </> : null}
  </section>;
}
