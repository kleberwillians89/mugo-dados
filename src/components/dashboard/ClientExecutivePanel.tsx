import type { CentralView } from "../../app/studio";
import { getPathForRoute, navigateToAppRoute, type AppRoute } from "../../app/routes";
import { formatCurrency, formatInteger } from "../../app/dataFormat";
import HealthIndexCard from "../clipping/HealthIndexCard";

/** Home executiva: somente dados do tenant/intervalo já resolvidos pela Central. */
export default function ClientExecutivePanel({ view, month, clientName, healthStart, healthEnd, showHealth }: {
  view: CentralView;
  month: string;
  clientName: string;
  healthStart: string;
  healthEnd: string;
  showHealth: boolean;
}) {
  const n = view.numbers;
  const media = view.media;
  const clip = view.clipping;
  const commerceAvailable = n?.faturamento != null;
  const orders = n?.pedidos;
  const ticket = commerceAvailable && orders != null && orders > 0 ? n.faturamento! / orders : null;
  const invested = n?.investimento;
  const retorno = n?.retorno;
  const channels = media?.channels || [];
  const week = clip?.week?.current;
  const cards: { label: string; value: string; detail: string; route: AppRoute; emphasis?: boolean }[] = [
    { label: "Faturamento da loja", value: commerceAvailable ? formatCurrency(n!.faturamento) : "Sem dados", detail: n?.end ? `Apurado até ${n.end.slice(8, 10)}/${n.end.slice(5, 7)}` : "Fonte comercial no período", route: "ecommerce", emphasis: true },
    { label: "Pedidos", value: orders != null ? formatInteger(orders) : "Sem dados", detail: "Vendas registradas no período", route: "ecommerce" },
    { label: "Ticket médio estimado", value: ticket != null ? formatCurrency(ticket) : "Sem dados", detail: "Faturamento dividido por pedidos", route: "ecommerce" },
    { label: "Investimento em mídia", value: invested != null ? formatCurrency(invested) : "Sem dados", detail: "Investimento informado pelas fontes", route: "media" },
    { label: "Retorno por R$ 1 investido", value: retorno != null ? formatCurrency(retorno) : "Sem dados", detail: "Indicador da Central; não é faturamento", route: "media" },
  ];
  const alerts = view.alerts.filter(a => a.module !== "tasks" && a.module !== "calendar" && a.module !== "approval");
  const mediaStatus = channels.length ? `${channels.length} ${channels.length === 1 ? "canal acompanhado" : "canais acompanhados"}` : "Sem canais de mídia no período";
  return <div className="clientExecutive">
    <section className="clientExecutiveWelcome" aria-label="Panorama executivo">
      <div>
        <span className="clientExecutiveEyebrow">PANORAMA DO NEGÓCIO · {month.slice(5)}/{month.slice(0, 4)}</span>
        <h2>{clientName}, em perspectiva.</h2>
        <p>Uma visão do que sua marca conquistou, como a operação comercial está evoluindo e onde acompanhar os próximos resultados.</p>
      </div>
      <a className="clientExecutiveTextLink" href={getPathForRoute("intelligence")}>Explorar inteligência <span aria-hidden="true">↗</span></a>
    </section>

    <div className="clientExecutiveTop">
      <section className="clientExecutiveHealth" aria-label="Saúde da Marca">
        <div className="clientExecutiveSectionHead">
          <div><span className="clientExecutiveEyebrow">01 / MARCA</span><h2>Saúde da marca</h2></div>
          <a href={getPathForRoute("brand_health")}>Análise completa ↗</a>
        </div>
        {showHealth ? <HealthIndexCard start={healthStart} end={healthEnd} compact /> : <p>Este período ainda não começou.</p>}
      </section>
      <section className="clientExecutiveSnapshot" aria-label="Leitura do período">
        <span className="clientExecutiveEyebrow">LEITURA RÁPIDA</span>
        <h2>O que os dados já mostram</h2>
        {n ? <p>{n.pedidos != null ? `${formatInteger(n.pedidos)} ${n.pedidos === 1 ? "pedido registrado" : "pedidos registrados"}` : "Pedidos ainda não informados"} no período; {invested != null ? `${formatCurrency(invested)} de investimento em mídia` : "investimento em mídia não disponível"}. Consulte cada canal para entender a performance.</p>
          : <p>O resumo comercial ainda não está disponível para este período. Acompanhe os canais conectados pelos relatórios especializados.</p>}
        <div className="clientExecutiveSnapshotFooter">
          <span>{commerceAvailable ? "Dados comerciais disponíveis" : "Cobertura comercial pendente"}</span>
          <button type="button" onClick={() => navigateToAppRoute("channels")}>Ver canais ↗</button>
        </div>
      </section>
    </div>

    <section className="clientExecutiveResults" aria-label="Resultados do negócio">
      <div className="clientExecutiveSectionHead"><div><span className="clientExecutiveEyebrow">02 / RESULTADOS</span><h2>Seu negócio em números</h2></div><small>Indicadores do período selecionado</small></div>
      <div className="clientExecutiveKpis">{cards.map(c => <button key={c.label} type="button" className={`clientExecutiveKpi${c.emphasis ? " is-main" : ""}`} onClick={() => navigateToAppRoute(c.route)}>
        <span>{c.label}</span><strong>{c.value}</strong><small>{c.detail}</small><span className="clientExecutiveKpiArrow" aria-hidden="true">↗</span>
      </button>)}</div>
      {n?.melhor_campanha ? <div className="clientExecutiveBest"><span>DESTAQUE COMERCIAL</span><strong>{n.melhor_campanha.campanha}</strong><p>{formatInteger(n.melhor_campanha.pedidos)} pedidos · {formatCurrency(n.melhor_campanha.vendas)} em vendas atribuídas no registro</p></div> : null}
    </section>

    <section className="clientExecutiveChannelSection" aria-label="Performance por frente">
      <div className="clientExecutiveSectionHead"><div><span className="clientExecutiveEyebrow">03 / CANAIS</span><h2>Marketing e presença digital</h2></div><small>{mediaStatus}</small></div>
      <div className="clientExecutiveChannelGrid">
        <article className="clientExecutiveChannel">
          <div><span className="clientExecutiveChannelIcon">↗</span><strong>Mídia paga</strong></div>
          <p>{channels.length ? "Investimento e retorno por canal no planejamento de mídia." : "Consulte os relatórios de Meta Ads e Google Ads para os indicadores detalhados."}</p>
          {channels.length ? <ul>{channels.slice(0, 4).map(c => <li key={c.channel}><span>{c.label}</span><strong>{formatCurrency(c.spent)}</strong></li>)}</ul> : null}
          <button type="button" onClick={() => navigateToAppRoute("media")}>Abrir mídia ↗</button>
        </article>
        <article className="clientExecutiveChannel">
          <div><span className="clientExecutiveChannelIcon">◎</span><strong>Redes sociais</strong></div>
          <p>Alcance, interações, seguidores e conteúdos com melhor desempenho.</p>
          <button type="button" onClick={() => navigateToAppRoute("social_report")}>Ver desempenho social ↗</button>
        </article>
        <article className="clientExecutiveChannel">
          <div><span className="clientExecutiveChannelIcon">◫</span><strong>Site e e-commerce</strong></div>
          <p>{commerceAvailable ? "Vendas registradas no período e indicadores da loja." : "Acompanhe tráfego, jornada de compra e conversões quando houver dados."}</p>
          <button type="button" onClick={() => navigateToAppRoute("ecommerce")}>Ver loja ↗</button>
        </article>
        <article className="clientExecutiveChannel">
          <div><span className="clientExecutiveChannelIcon">◉</span><strong>Reputação da marca</strong></div>
          {week ? <p>{formatInteger(week.marca ?? 0)} menções acompanhadas nos últimos 7 dias, com {formatInteger(week.positivo ?? 0)} positivas e {formatInteger(week.negativo ?? 0)} negativas.</p> : <p>Menções, sentimento e assuntos relevantes da marca.</p>}
          <button type="button" onClick={() => navigateToAppRoute("clipping")}>Ver reputação ↗</button>
        </article>
      </div>
    </section>
    {alerts.length ? <section className="clientExecutiveSignals" aria-label="Sinais de atenção"><div className="clientExecutiveSectionHead"><h2>Sinais que merecem atenção</h2></div><ul>{alerts.slice(0, 3).map(a => <li key={`${a.module}:${a.text}`}>{a.text}</li>)}</ul></section> : null}
  </div>;
}
