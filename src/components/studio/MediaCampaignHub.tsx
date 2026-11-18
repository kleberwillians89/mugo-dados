import type { Brief } from "../../app/briefs";

type Props = {
  briefs: Brief[];
  selectedId: string;
  loading: boolean;
  error: string | null;
  canManage: boolean;
  busy: boolean;
  onSelect: (id: string) => void;
  onRefresh: () => void;
  onEditBrief: () => void;
  onMeta: (brief: Brief) => void;
  onGoogle: (brief: Brief) => void;
};

const eligible = (brief: Brief) => brief.status !== "arquivado";
const formatBudget = (value?: number | null) => typeof value === "number" && value > 0
  ? value.toLocaleString("pt-BR", {style: "currency", currency: "BRL"}) : "Definir no editor";

export default function MediaCampaignHub({
  briefs, selectedId, loading, error, canManage, busy, onSelect, onRefresh, onEditBrief, onMeta, onGoogle,
}: Props) {
  const available = briefs.filter(eligible);
  const selected = available.find((b) => b.id === selectedId) || null;
  const detail = selected?.brief;
  return <section className="mediaHub" aria-labelledby="media-hub-title">
    <header className="mediaHubHeader">
      <div>
        <span className="mediaHubEyebrow">MÍDIA ON / CENTRAL DE CAMPANHAS</span>
        <h2 id="media-hub-title">Do briefing à campanha.</h2>
        <p>Escolha o planejamento, revise as informações e prepare anúncios sem começar do zero.</p>
      </div>
      <button type="button" className="ds-button" onClick={onRefresh} disabled={loading}>{loading ? "Atualizando…" : "Atualizar briefings"}</button>
    </header>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    <div className="mediaHubGrid">
      <div className="mediaHubBrief">
        <div className="mediaHubCardHeading"><span className="mediaHubStep">01 / BRIEFING</span><span className="mediaHubPill">{selected ? "Briefing localizado" : "Aguardando seleção"}</span></div>
        <h3>Estratégia que vai orientar os anúncios</h3>
        <label htmlFor="media-hub-select" className="mediaHubLabel">Briefing da empresa
          <select id="media-hub-select" value={selected?.id || ""} disabled={loading || !available.length} onChange={(e) => onSelect(e.target.value)}>
            {!available.length ? <option value="">Nenhum briefing disponível</option> : null}
            {available.map((b) => <option key={b.id} value={b.id}>{b.brief.title || "Briefing sem título"} · {new Date(b.created_at).toLocaleDateString("pt-BR")}</option>)}
          </select>
        </label>
        {detail ? <>
          <div className="mediaHubBriefSummary">
            <strong>{detail.title}</strong>
            <p>{detail.summary || detail.client_summary || selected?.request || "O briefing pode ser consultado na área Estratégia."}</p>
          </div>
          <div className="mediaHubFacts">
            <div><span>Objetivo</span><b>{detail.media?.objective || detail.objective || "Ajustar na campanha"}</b></div>
            <div><span>Verba prevista</span><b>{formatBudget(detail.media?.budget)}</b></div>
            <div><span>Público</span><b>{detail.audience || "Ajustar na campanha"}</b></div>
          </div>
          <details className="mediaHubDetails">
            <summary>Ver briefing aplicado e direcionamento</summary>
            {detail.key_message ? <p><b>Mensagem:</b> {detail.key_message}</p> : null}
            {detail.goal ? <p><b>Meta:</b> {detail.goal}</p> : null}
            {detail.deadline ? <p><b>Prazo:</b> {detail.deadline.slice(0,10).split("-").reverse().join("/")}</p> : null}
            {detail.deliverables?.length ? <p><b>Entregáveis:</b> {detail.deliverables.join(" · ")}</p> : null}
            {detail.avoid?.length ? <p><b>Evitar:</b> {detail.avoid.join(" · ")}</p> : null}
            <p><b>Pedido:</b> {selected?.request}</p>
          </details>
        </> : <p className="mediaHubEmpty">{loading ? "Buscando briefings desta empresa…" : "Crie um briefing em Estratégia para começar. Você poderá vinculá-lo aqui sem cadastrá-lo novamente."}</p>}
        {canManage ? <button type="button" className="ds-button mediaHubSecondary" onClick={onEditBrief}>{selected ? "Editar briefing original" : "Criar briefing"}</button> : null}
      </div>
      <div className="mediaHubLaunch">
        <span className="mediaHubStep">02 / PREPARAR CAMPANHA</span>
        <h3>Escolha onde anunciar</h3>
        <p>Os dados do briefing serão usados como ponto de partida. Os ajustes finais continuam nos editores já existentes.</p>
        <button type="button" className="mediaHubAction" disabled={!selected || busy || !canManage} onClick={() => { if(selected) onMeta(selected); }}>
          <span><b>Meta Ads</b><small>Montar campanha, público e criativos</small></span><span aria-hidden="true">↗</span>
        </button>
        <button type="button" className="mediaHubAction is-google" disabled={!selected || busy || !canManage} onClick={() => { if(selected) onGoogle(selected); }}>
          <span><b>Google Ads</b><small>Iniciar rascunho de Pesquisa com o briefing</small></span><span aria-hidden="true">↗</span>
        </button>
        <p className="mediaHubSafety">A criação de rascunhos não publica anúncios. A revisão e a publicação continuam exigindo confirmação.</p>
      </div>
    </div>
    <p className="mediaHubBottom"><b>03 / EDITAR E PUBLICAR</b> Os rascunhos aparecem logo abaixo, em cards com os botões <b>Editar</b>, <b>Revisar</b> e <b>Criativos</b>.</p>
  </section>;
}
