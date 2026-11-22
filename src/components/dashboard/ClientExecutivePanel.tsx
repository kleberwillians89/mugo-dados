import type { CentralView } from "../../app/studio";
import { STAGES, STUDIO_FORMATS, localParts } from "../../app/studio";
import { navigateToAppRoute, type AppRoute } from "../../app/routes";
import { formatCurrency, formatInteger } from "../../app/dataFormat";
import HealthIndexCard from "../clipping/HealthIndexCard";

const MONTH_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const FLOW = ["rascunho", "revisao_interna", "com_cliente", "ajuste", "aprovado", "publicado"];
const Empty = ({ children }: { children: React.ReactNode }) => <p className="dashboardEmpty">{children}</p>;

function percent(current: number | null | undefined, previous: number | null | undefined) {
  return current == null || previous == null || previous === 0 ? null : ((current - previous) / Math.abs(previous)) * 100;
}
function Delta({ current, previous, inverse = false }: { current: number | null | undefined; previous: number | null | undefined; inverse?: boolean }) {
  const value = percent(current, previous);
  if (value == null) return <span className="dashboardDelta is-neutral">Sem comparação</span>;
  const good = inverse ? value <= 0 : value >= 0;
  return <span className={`dashboardDelta ${good ? "is-good" : "is-bad"}`}>{value >= 0 ? "↗" : "↘"} {Math.abs(value).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</span>;
}
function MetricCard({ label, value, current, previous, route, definition }: { label: string; value: string; current?: number | null; previous?: number | null; route: AppRoute; definition: string }) {
  return <button type="button" className="dashboardMetric" onClick={() => navigateToAppRoute(route)}><span>{label}</span><strong>{value}</strong><Delta current={current} previous={previous} /><small>{definition}</small></button>;
}

/** Dashboard gerencial: compõe somente leituras já autorizadas e não dispara IA. */
export default function ClientExecutivePanel({ view, healthStart, healthEnd, showHealth }: { view: CentralView; month: string; clientName: string; healthStart: string; healthEnd: string; showHealth: boolean }) {
  const n = view.numbers;
  const previous = n?.previous;
  const ticket = n?.ticket_medio ?? (n?.faturamento != null && n?.pedidos ? n.faturamento / n.pedidos : null);
  const previousTicket = previous?.ticket_medio ?? (previous?.faturamento != null && previous?.pedidos ? previous.faturamento / previous.pedidos : null);
  const paidRoas = n?.vendas_midia_paga != null && n?.investimento ? n.vendas_midia_paga / n.investimento : null;
  const previousPaidRoas = previous?.vendas_midia_paga != null && previous?.investimento ? previous.vendas_midia_paga / previous.investimento : null;
  const cal = view.calendar;
  const tasks = view.tasks;
  const social = view.social;
  const history = view.approval_history?.months || [];
  const chartMax = Math.max(1, ...history.flatMap((item) => [item.approved, item.internal_changes, item.client_changes]));
  const workload = tasks?.workload;
  const maxDepartment = Math.max(1, ...(workload?.departments || []).map((item) => item.tasks));

  return <div className="clientExecutive">
    <section className="dashboardSection dashboardHealth clientExecutiveHealth" aria-label="Saúde da marca"><header><div><span>01 / MARCA</span><h2>Saúde da marca</h2></div><small>Indicadores do período selecionado</small></header>{showHealth ? <HealthIndexCard start={healthStart} end={healthEnd} compact /> : <Empty>Este período ainda não começou.</Empty>}</section>

    <section className="dashboardSection" aria-label="Números do negócio"><header><div><span>02 / RESULTADOS</span><h2>Números do negócio</h2></div><small>Comparação com período equivalente anterior</small></header><div className="dashboardMetrics">
      <MetricCard label="Faturamento da loja" value={n?.faturamento != null ? formatCurrency(n.faturamento) : "Sem dados"} current={n?.faturamento} previous={previous?.faturamento} route="ecommerce" definition="Receita registrada pela fonte comercial." />
      <MetricCard label="Pedidos" value={n?.pedidos != null ? formatInteger(n.pedidos) : "Sem dados"} current={n?.pedidos} previous={previous?.pedidos} route="ecommerce" definition="Pedidos registrados no período." />
      <MetricCard label="Ticket médio" value={ticket != null ? formatCurrency(ticket) : "Sem dados"} current={ticket} previous={previousTicket} route="ecommerce" definition="Faturamento dividido por pedidos." />
      <MetricCard label="Investimento em mídia" value={n?.investimento != null ? formatCurrency(n.investimento) : "Sem dados"} current={n?.investimento} previous={previous?.investimento} route="media" definition="Investimento informado pelas fontes." />
      <MetricCard label="Retorno / R$ investido" value={n?.retorno != null ? `${n.retorno.toLocaleString("pt-BR")}×` : "Sem dados"} current={n?.retorno} previous={previous?.retorno} route="media" definition="Faturamento total ÷ investimento; não é ROAS atribuído." />
    </div></section>

    <section className="dashboardSection" aria-label="Marketing e presença digital"><header><div><span>03 / CANAIS</span><h2>Marketing e presença digital</h2></div><small>Somente métricas não resumidas acima</small></header><div className="dashboardChannels">
      <article><div className="dashboardCardTitle"><i>↗</i><h3>Mídia paga</h3><small>Canais conectados</small></div><div className="dashboardInlineMetrics"><div><span>Investimento</span><strong>{n?.investimento != null ? formatCurrency(n.investimento) : "—"}</strong></div><div><span>Receita atribuída</span><strong>{n?.vendas_midia_paga != null ? formatCurrency(n.vendas_midia_paga) : "—"}</strong></div><div><span>ROAS atribuído</span><strong>{paidRoas != null ? `${paidRoas.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}×` : "—"}</strong><Delta current={paidRoas} previous={previousPaidRoas} /></div></div><p>Receita e ROAS só aparecem quando a fonte comercial informa atribuição paga.</p></article>
      <article><div className="dashboardCardTitle"><i>◎</i><h3>Redes sociais</h3><small>Orgânico persistido</small></div>{social ? <div className="dashboardInlineMetrics"><div><span>Alcance</span><strong>{social.reach != null ? formatInteger(social.reach) : "—"}</strong><Delta current={social.reach} previous={social.previous?.reach} /></div><div><span>Interações</span><strong>{social.interactions != null ? formatInteger(social.interactions) : "—"}</strong><Delta current={social.interactions} previous={social.previous?.interactions} /></div><div><span>Novos seguidores</span><strong>{social.new_followers != null ? formatInteger(social.new_followers) : "—"}</strong><Delta current={social.new_followers} previous={social.previous?.new_followers} /></div></div> : <Empty>Sem snapshots orgânicos suficientes neste período.</Empty>}<p>Alcance e interações vêm de {social?.days ?? 0} dia(s) com snapshot; novos seguidores vêm do relatório mensal salvo.</p></article>
    </div></section>

    <section className="dashboardSection" aria-label="Detalhes operacionais"><header><div><span>04 / OPERAÇÃO</span><h2>Detalhes operacionais</h2></div><small>Sempre visível</small></header>
      <article className="dashboardSurface"><div className="dashboardCardTitle"><h3>Fluxo de trabalho</h3><small>Demandas por etapa</small></div>{cal ? <ul className="dashboardStages">{FLOW.map((stage) => <li key={stage} className={`is-${stage}`}><span>{STAGES[stage as keyof typeof STAGES] || stage}</span><strong>{cal.counts[stage] ?? 0}</strong></li>)}</ul> : <Empty>Fluxo do calendário indisponível.</Empty>}</article>
      <div className="dashboardOperationalGrid"><article className="dashboardSurface"><div className="dashboardCardTitle"><h3>Aprovados × alterações</h3><small>Últimos 6 meses</small></div>{history.length ? <><div className="dashboardChart" role="img" aria-label="Eventos de aprovação e alteração nos últimos seis meses">{history.map((item) => <div key={item.month} className="dashboardChartGroup"><div><i className="is-approved" style={{ height: `${(item.approved / chartMax) * 100}%` }} title={`${item.approved} aprovações`} /><i className="is-internal" style={{ height: `${(item.internal_changes / chartMax) * 100}%` }} title={`${item.internal_changes} alterações internas`} /><i className="is-client" style={{ height: `${(item.client_changes / chartMax) * 100}%` }} title={`${item.client_changes} alterações do cliente`} /></div><span>{MONTH_SHORT[Number(item.month.slice(5)) - 1]}</span></div>)}</div><div className="dashboardLegend"><span className="is-approved">Aprovados</span><span className="is-internal">Alterações internas</span><span className="is-client">Alterações do cliente</span></div><p>{view.approval_history?.definition}</p></> : <Empty>Histórico de eventos indisponível.</Empty>}</article>
        <article className="dashboardSurface"><div className="dashboardCardTitle"><h3>Próximas entregas</h3><small>{(cal?.upcoming.length || 0) + (tasks?.next?.length || 0)} previstas</small></div>{cal?.upcoming.length || tasks?.next?.length ? <ul className="dashboardDeliveries">{cal?.upcoming.map((post) => { const when = localParts(post.scheduled_at); return <li key={post.id}><time>{when.label}</time><div><strong>{post.title}</strong><span>{STUDIO_FORMATS[post.format]} · {STAGES[post.stage as keyof typeof STAGES] || post.stage}</span></div></li>; })}{tasks?.next?.map((task) => <li key={`${task.title}:${task.due_date}`}><time>{task.due_date ? `${task.due_date.slice(8, 10)}/${task.due_date.slice(5, 7)}` : "—"}</time><div><strong>{task.title}</strong><span>Tarefa · {task.status}</span></div></li>)}</ul> : <Empty>Nenhuma entrega futura registrada.</Empty>}</article></div>
    </section>

    <section className="dashboardSection" aria-label="Onde agir agora"><header><div><span>05 / GESTÃO</span><h2>Onde agir agora</h2></div><small>Alertas determinísticos, sem análise de IA</small></header><article className="dashboardSurface"><div className="dashboardCardTitle"><h3>Atenção necessária</h3><small>{view.alerts.length} ponto(s)</small></div>{view.alerts.length ? <ul className="dashboardAlerts">{view.alerts.slice(0, 5).map((alert) => <li key={`${alert.module}:${alert.text}`} className={`is-${alert.level}`}><i>{alert.level === "atencao" ? "!" : "i"}</i><span>{alert.text}</span></li>)}</ul> : <Empty>Nenhum alerta calculável com os dados atuais.</Empty>}</article></section>

    <section className="dashboardSection" aria-label="Carga por departamento"><header><div><span>06 / OPERAÇÃO</span><h2>Carga por departamento</h2></div><small>Contagem de tarefas abertas; não representa capacidade</small></header><article className="dashboardSurface">{workload?.departments.length ? <ul className="dashboardWorkload">{workload.departments.map((item) => <li key={item.name}><span>{item.name}</span><div><i style={{ width: `${(item.tasks / maxDepartment) * 100}%` }} /></div><strong>{item.tasks} tarefa(s)</strong></li>)}</ul> : <Empty>{view.agency ? "Sem tarefas atribuídas por departamento." : "Indicador indisponível: o cadastro atual não distingue com segurança equipe do cliente e Equipe Mugô."}</Empty>}</article></section>

    <section className="dashboardSection" aria-label="Carga da equipe"><header><div><span>07 / PESSOAS</span><h2>Carga da equipe</h2></div><small>Somente responsáveis autorizados deste tenant</small></header><article className="dashboardSurface">{workload?.people.length ? <div className="dashboardPeople">{workload.people.slice(0, 8).map((person) => <div key={person.name}><span>{person.name}</span><strong>{person.tasks} demanda(s)</strong><small>{person.late} atrasada(s) · {person.rework} com retrabalho</small></div>)}</div> : <Empty>{view.agency ? "Sem responsáveis com tarefas abertas." : "Carga individual não exibida para evitar exposição de integrantes da Equipe Mugô."}</Empty>}</article></section>
  </div>;
}
