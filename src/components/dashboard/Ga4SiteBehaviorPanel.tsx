import type { Ga4EventGroup, Ga4ReportResponse } from "../../app/types";
import { formatSelectedPeriodLabel, type SelectedPeriodRange } from "../../app/periodRange";

type Props = {
  report: Ga4ReportResponse | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  updatedAtLabel?: string | null;
  period?: SelectedPeriodRange | null;
};

function fmt(n: number) {
  try {
    return n.toLocaleString("pt-BR");
  } catch {
    return String(n);
  }
}

function fmtPct(n: number) {
  return `${Number.isFinite(n) ? n.toFixed(n >= 10 ? 0 : 1) : "0.0"}%`;
}

function hasGa4Data(report: Ga4ReportResponse | null) {
  if (!report) return false;
  return (
    report.summary.sessions > 0 ||
    report.summary.event_count > 0
  );
}

function SummaryCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="ga4SummaryCard">
      <span className="smallMuted">{label}</span>
      <strong>{value}</strong>
      {hint ? <span className="ga4SummaryHint">{hint}</span> : null}
    </div>
  );
}

function JourneyStep({
  label,
  value,
  rate,
  hint,
}: {
  label: string;
  value: number;
  rate?: number | null;
  hint: string;
}) {
  return (
    <div className="ga4JourneyStep">
      <span className="smallMuted">{label}</span>
      <strong>{fmt(value)}</strong>
      <span className="ga4JourneyHint">{hint}</span>
      {typeof rate === "number" ? <span className="ga4JourneyRate">{fmtPct(rate)}</span> : null}
    </div>
  );
}

function GroupTable({ group }: { group: Ga4EventGroup }) {
  return (
    <div className="ga4GroupCard">
      <div className="ga4GroupHead">
        <div>
          <div className="h1">{group.title}</div>
          <div className="p">{group.description}</div>
        </div>
        <div className="ga4GroupSummary">
          <span>{fmt(group.total_events)} ocorrências</span>
          <span>{fmt(group.total_users)} usuários</span>
        </div>
      </div>

      <div className="tableWrap ga4TableWrap">
        <table className="table ga4GroupTable">
          <thead>
            <tr>
              <th>Evento</th>
              <th>Ocorrências</th>
              <th>Usuários</th>
            </tr>
          </thead>
          <tbody>
            {group.items.map((item) => (
              <tr key={item.event_name}>
                <td>
                  <div className="cellTitle">{item.label}</div>
                  {item.description ? <div className="cellMuted">{item.description}</div> : null}
                </td>
                <td>{fmt(item.event_count)}</td>
                <td>{fmt(item.total_users)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Ga4Skeleton() {
  return (
    <div className="ga4SectionBody">
      <div className="ga4SummaryGrid">
        <div className="skeleton skeletonKpi" />
        <div className="skeleton skeletonKpi" />
        <div className="skeleton skeletonKpi" />
        <div className="skeleton skeletonKpi" />
      </div>
      <div className="ga4JourneyGrid">
        <div className="skeleton skeletonKpi" />
        <div className="skeleton skeletonKpi" />
        <div className="skeleton skeletonKpi" />
        <div className="skeleton skeletonKpi" />
        <div className="skeleton skeletonKpi" />
      </div>
      <div className="ga4GroupsGrid">
        <div className="skeleton skeletonTall" />
        <div className="skeleton skeletonTall" />
        <div className="skeleton skeletonTall" />
      </div>
    </div>
  );
}

export default function Ga4SiteBehaviorPanel({
  report,
  loading,
  refreshing,
  error,
  updatedAtLabel,
  period,
}: Props) {
  const hasData = hasGa4Data(report);

  return (
    <div className="card cardWide ga4SectionCard">
      <div className="sectionHeader">
        <div>
          <div className="h1">Comportamento GA4</div>
          <div className="p">
            Leitura executiva do GA4 para entender navegação, intenção de compra e sinais de engajamento no site do cliente ativo.
          </div>
        </div>
        <div className="dashboardSectionMeta">
          <span className="pill">
            {period ? `Fonte: GA4 · ${formatSelectedPeriodLabel(period)}` : "Fonte: GA4"}
          </span>
          {updatedAtLabel ? <span className="dashboardTimestamp">{updatedAtLabel}</span> : null}
          {refreshing ? <span className="pill">Atualizando...</span> : null}
        </div>
      </div>

      {loading && !report ? <Ga4Skeleton /> : null}

      {error && !report ? (
        <div className="smallMuted">Não foi possível carregar a leitura de comportamento do site agora.</div>
      ) : null}

      {!loading && report && !hasData ? (
        <div className="smallMuted">Ainda não há dados de comportamento do site para este período.</div>
      ) : null}

      {report && hasData ? (
        <div className="ga4SectionBody">
          {error ? <div className="smallMuted ga4InlineNotice">Atualização parcial. Mantendo a última leitura disponível.</div> : null}

          <div className="ga4SummaryGrid">
            <SummaryCard
              label="Sessões do site"
              value={fmt(report.summary.sessions)}
              hint={`${fmt(report.summary.active_users)} usuários ativos`}
            />
            <SummaryCard
              label="Eventos observados"
              value={fmt(report.summary.event_count)}
              hint={`${fmt(report.summary.total_users)} usuários totais`}
            />
            <SummaryCard
              label="Usuários ativos"
              value={fmt(report.summary.active_users)}
              hint={`${fmt(report.summary.total_users)} usuários totais`}
            />
            <SummaryCard
              label="Taxa compra / view_item"
              value={fmtPct(report.commerce_journey.summary.purchase_rate_from_view_item)}
              hint="Eficiência do funil comercial"
            />
          </div>

          <div className="ga4JourneyCard">
            <div className="ga4JourneyHead">
              <div>
                <div className="h1">Funil principal do site</div>
                <div className="p">Etapas mais relevantes da jornada comercial, organizadas para leitura rápida em reunião.</div>
              </div>
              <span className="pill">Tracking comportamental GA4</span>
            </div>

            <div className="ga4JourneyGrid">
              <JourneyStep
                label="Visualizou produto"
                value={report.commerce_journey.summary.view_item}
                hint="Base do funil"
              />
              <JourneyStep
                label="Adicionou ao carrinho"
                value={report.commerce_journey.summary.add_to_cart}
                rate={report.commerce_journey.summary.add_to_cart_rate}
                hint="Conversão a partir de produto"
              />
              <JourneyStep
                label="Iniciou checkout"
                value={report.commerce_journey.summary.begin_checkout}
                rate={report.commerce_journey.summary.checkout_rate}
                hint="Avanço do carrinho"
              />
              <JourneyStep
                label="Informou pagamento"
                value={report.commerce_journey.summary.add_payment_info}
                rate={report.commerce_journey.summary.payment_info_rate}
                hint="Checkout qualificado"
              />
              <JourneyStep
                label="Evento purchase GA4"
                value={report.commerce_journey.summary.purchase}
                rate={report.commerce_journey.summary.purchase_rate}
                hint="Conversão final"
              />
            </div>
          </div>

          <div className="ga4GroupsGrid">
            <GroupTable group={report.behavior} />
            <GroupTable group={report.merchandising} />
            <GroupTable group={report.engagement} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
