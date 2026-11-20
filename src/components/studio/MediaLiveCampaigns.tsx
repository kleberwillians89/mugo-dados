import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { getLiveCampaigns, type LiveCampaign, type LiveCampaignState } from "../../app/metaAds";

const STATE: Record<LiveCampaignState, { label: string; tone: string }> = {
  no_ar: { label: "No ar", tone: "is-on" }, pausada: { label: "Pausada", tone: "is-off" },
  em_analise: { label: "Em análise na Meta", tone: "is-wait" }, com_problema: { label: "Com problema", tone: "is-bad" },
  reprovada: { label: "Reprovada pela Meta", tone: "is-bad" }, encerrada: { label: "Encerrada", tone: "is-off" },
  desconhecido: { label: "Status indisponível", tone: "is-off" },
};
const OBJECTIVE: Record<string, string> = {
  vendas: "Vendas", leads: "Cadastros", trafego: "Tráfego para o site", alcance: "Alcance", whatsapp: "Conversas no WhatsApp",
  retencao: "Clientes que já compraram", remarketing: "Remarketing",
};
const brl = (n: number | null | undefined) => n == null ? "—" : n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const int = (n: number | null | undefined) => n == null ? "—" : n.toLocaleString("pt-BR");
const day = (iso: string) => iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "";

/** O que está sendo veiculado: para o cliente acompanhar (somente leitura, sem verba nem botões). */
export default function MediaLiveCampaigns() {
  const clientId = getActiveClientId();
  const [items, setItems] = useState<LiveCampaign[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<LiveCampaignState | "all">("no_ar");

  useEffect(() => {
    let alive = true;
    setFilter("no_ar"); setItems(null); setError(null);
    getLiveCampaigns().then((r) => { if (alive && getActiveClientId() === clientId) setItems(r.campaigns); })
      .catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "Não foi possível carregar as campanhas."); });
    return () => { alive = false; };
  }, [clientId]);

  const visible = (items || []).filter((c) => filter === "all" || c.state === filter);

  return <section className="ds-section mediaLive" aria-labelledby="media-live-title">
    <h2 id="media-live-title">O que está sendo veiculado</h2>
    <p className="ds-footnote">Campanhas que a Mugô colocou no Meta (Instagram e Facebook), com o anúncio e os números desde o início.</p>
    <label className="ds-caption" style={{ display: "block", margin: "14px 0" }}>Filtrar campanhas
      <select aria-label="Filtrar campanhas por status" value={filter} onChange={(e) => setFilter(e.target.value as LiveCampaignState | "all")} style={{ display: "block", minHeight: 40, marginTop: 6 }}>
        <option value="no_ar">Ativas (padrão)</option>
        <option value="pausada">Pausadas / desativadas</option>
        <option value="encerrada">Encerradas</option>
        <option value="em_analise">Em análise</option>
        <option value="com_problema">Com problemas</option>
        <option value="reprovada">Reprovadas</option>
        <option value="desconhecido">Status indisponível</option>
        <option value="all">Todas as campanhas</option>
      </select>
    </label>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {!items && !error ? <p role="status">Buscando as campanhas na Meta…</p> : null}
    {items && !visible.length ? <p className="ds-noticeText">Nenhuma campanha neste status. Use o filtro para consultar as pausadas, encerradas ou todas.</p> : null}
    {visible.length ? <div className="mediaLiveGrid">{visible.map((c) => {
      const creative = c.creatives[0];
      return <article key={c.id} className="mediaLiveCard">
        <div className="mediaLiveMedia">
          {creative?.image_url ? <img src={creative.image_url} alt="" loading="lazy" />
            : creative?.video_url ? <video src={`${creative.video_url}#t=1`} muted playsInline preload="metadata" /> : <span>Sem prévia</span>}
          {c.creatives.length > 1 ? <small className="mediaLiveCount">{c.creatives.length} anúncios</small>
            : creative?.cards ? <small className="mediaLiveCount">Carrossel · {creative.cards}</small> : null}
        </div>
        <div className="mediaLiveBody">
          <span className={`mediaLiveState ${STATE[c.state].tone}`}>{STATE[c.state].label}</span>
          <h3>{c.name}</h3>
          <small>{OBJECTIVE[c.objective] || c.objective} · {brl(c.daily_budget)}/dia · {day(c.start_date)} a {day(c.end_date)}</small>
          {c.headline ? <b className="mediaLiveHeadline">{c.headline}</b> : null}
          {c.primary_text ? <p className="mediaLiveText">{c.primary_text}</p> : null}
          {c.results ? <dl className="mediaLiveNumbers">
            <div><dt>Investido</dt><dd>{brl(c.results.spend)}</dd></div>
            <div><dt>Pessoas alcançadas</dt><dd>{int(c.results.reach)}</dd></div>
            <div><dt>{c.results.result_label}</dt><dd>{int(c.results.results)}</dd></div>
            <div><dt>Custo por resultado</dt><dd>{brl(c.results.cost_per_result)}</dd></div>
          </dl> : <small className="ds-footnote">Números da Meta indisponíveis agora.</small>}
        </div>
      </article>;
    })}</div> : null}
  </section>;
}
