import { useEffect, useMemo, useState } from "react";
import { getClients, type ClientMembership } from "../../app/api";
import { readMetaCampaignOverview, type MetaOverviewCampaign } from "../../app/metaAds";
import "./MediaAllClientsCampaigns.css";

type CampaignRow = MetaOverviewCampaign & { client_id: string; client_name: string };
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

export default function MediaAllClientsCampaigns() {
  const [companies, setCompanies] = useState<ClientMembership[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignRow[]>([]);
  const [companyId, setCompanyId] = useState("all");
  const [status, setStatus] = useState<CampaignFilter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [failedCompanies, setFailedCompanies] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(null); setFailedCompanies([]); setCampaigns([]);
    (async () => {
      try {
        // A API de empresas lista somente organizações vinculadas ao usuário autenticado.
        // A leitura de cada conta exige agency_admin no próprio backend.
        const response = await getClients();
        if (!active) return;
        const linked = response.clients.filter((c) => c.client_id && c.role === "agency_admin");
        setCompanies(linked);
        const found: CampaignRow[] = [];
        const failed: string[] = [];
        // Limitar simultaneidade para não sobrecarregar a API Meta nas agências com muitos clientes.
        for (let start = 0; start < linked.length && active; start += 3) {
          const batch = linked.slice(start, start + 3);
          const results = await Promise.allSettled(batch.map((company) => readMetaCampaignOverview(company.client_id)));
          if (!active) return;
          results.forEach((result, index) => {
            const company = batch[index];
            if (result.status === "fulfilled") {
              found.push(...result.value.campaigns.map((campaign) => ({
                ...campaign, client_id: company.client_id, client_name: company.name,
              })));
            } else {
              failed.push(company.name);
            }
          });
        }
        if (active) {
          setCampaigns(found);
          setFailedCompanies(failed);
        }
      } catch {
        if (active) setError("Não foi possível carregar as empresas. Tente atualizar.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  const filtered = useMemo(() => campaigns.filter((campaign) => {
    if (companyId !== "all" && campaign.client_id !== companyId) return false;
    if (status !== "all" && campaignCategory(campaign) !== status) return false;
    return !search.trim() || `${campaign.name} ${campaign.client_name}`.toLocaleLowerCase("pt-BR").includes(search.trim().toLocaleLowerCase("pt-BR"));
  }), [campaigns, companyId, status, search]);

  const counts = useMemo(() => {
    const scoped = companyId === "all" ? campaigns : campaigns.filter((c) => c.client_id === companyId);
    return FILTERS.reduce((acc, f) => {
      acc[f.value] = f.value === "all" ? scoped.length : scoped.filter((c) => campaignCategory(c) === f.value).length;
      return acc;
    }, {} as Record<CampaignFilter, number>);
  }, [campaigns, companyId]);

  return <section className="mediaAllClients" aria-labelledby="media-all-clients-heading">
    <div className="mediaAllClientsHeading">
      <div>
        <span className="mediaAllClientsEyebrow">MÍDIA ON / VISÃO DA AGÊNCIA</span>
        <h2 id="media-all-clients-heading">Campanhas de todos os clientes</h2>
        <p>Consulte campanhas das contas Meta vinculadas à equipe Mugô. Filtros não pausam nem ativam anúncios.</p>
      </div>
      <button className="ds-button" type="button" disabled={loading} onClick={() => setRefreshKey((k) => k + 1)}>Atualizar campanhas</button>
    </div>
    <div className="mediaAllClientsFilters">
      <label>Empresa
        <select aria-label="Filtrar por empresa" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
          <option value="all">Todas as empresas</option>
          {companies.map((c) => <option key={c.client_id} value={c.client_id}>{c.name}</option>)}
        </select>
      </label>
      <label>Status
        <select aria-label="Filtrar por status" value={status} onChange={(e) => setStatus(e.target.value as CampaignFilter)}>
          {FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label} ({counts[f.value] || 0})</option>)}
        </select>
      </label>
      <label>Buscar campanha
        <input aria-label="Buscar campanha" placeholder="Nome da campanha" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
    </div>
    {loading ? <p role="status">Consultando campanhas das empresas autorizadas…</p> : null}
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {!loading && failedCompanies.length ? <p role="status" className="mediaAllClientsWarning">
      Não foi possível consultar {failedCompanies.length} empresa(s): {failedCompanies.join(", ")}. Os totais abaixo são parciais.
    </p> : null}
    {!loading && !error ? <>
      <p className="mediaAllClientsTotal" role="status">{filtered.length.toLocaleString("pt-BR")} campanha(s) encontrada(s){companyId !== "all" ? " nesta empresa" : " nas empresas consultadas"}.</p>
      {filtered.length ? <div className="mediaAllClientsTableWrap">
        <table className="mediaAllClientsTable">
          <thead><tr><th>Empresa</th><th>Campanha</th><th>Status</th><th>Objetivo Meta</th><th>Verba diária</th></tr></thead>
          <tbody>{filtered.map((c) => {
            const category = campaignCategory(c);
            return <tr key={`${c.client_id}:${c.id}`}>
              <td>{c.client_name}</td>
              <td><strong>{c.name}</strong>{c.stop_time ? <small>Fim: {new Date(c.stop_time).toLocaleDateString("pt-BR")}</small> : null}</td>
              <td><span className={`mediaAllClientsState is-${category}`}>{labelFor(category)}</span></td>
              <td>{c.objective || "—"}</td><td>{money(c.daily_budget)}</td>
            </tr>;
          })}</tbody>
        </table>
      </div> : <p className="ds-noticeText">Nenhuma campanha corresponde aos filtros. Confira as conexões Meta das empresas e tente outro status.</p>}
      <p className="ds-footnote">Status consultados na Meta. Encerrada inclui campanhas arquivadas ou com data de término ultrapassada; campanhas sem acesso à Meta não entram nos totais.</p>
    </> : null}
  </section>;
}
