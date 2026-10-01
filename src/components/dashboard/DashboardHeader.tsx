import { Fragment } from "react";
import DayPeriodControl from "../DayPeriodControl";
import SegmentedControl from "../data/SegmentedControl";

type Props = {
  activeView: "meta" | "google";
  statusChips: Array<{
    label: string;
    connected?: boolean;
    refreshing?: boolean;
  }>;
  periodPreset: "day" | "7d" | "30d" | "month" | "custom";
  onSelectPeriodPreset?: (preset: "day" | "7d" | "30d" | "month") => void;
  refreshing?: boolean;
  backgroundRefreshing?: boolean;
  /** Navegação e saída vivem na sidebar global; mantidos só por compatibilidade. */
  onOpenMeta?: () => void;
  onOpenGoogleAnalytics?: () => void;
  onRefresh?: () => void;
  onLogout?: () => void | Promise<void>;
};

const PERIOD_OPTIONS: Array<{ id: "day" | "7d" | "30d" | "month"; label: string }> = [
  { id: "day", label: "Dia" },
  { id: "7d", label: "7 dias" },
  { id: "30d", label: "30 dias" },
  { id: "month", label: "Este mês" },
];

/** Controles da página (período, estado das fontes, atualização) — sem navegação. */
export default function DashboardHeader({
  statusChips,
  periodPreset,
  onSelectPeriodPreset,
  refreshing = false,
  backgroundRefreshing = false,
  onRefresh,
}: Props) {
  // Estado das fontes e atualização: uma linha operacional, discreta.
  const statusParts = [
    ...statusChips.map((chip) => ({
      key: chip.label,
      node: (
        <span className={`pageControlsStatusItem ${chip.connected ? "isConnected" : ""} ${chip.refreshing ? "isRefreshing" : ""}`.trim()}>
          {chip.label}
        </span>
      ),
    })),
    ...(backgroundRefreshing || refreshing
      ? [{ key: "background", node: <span className="pageControlsStatusItem isRefreshing">Atualizando em segundo plano</span> }]
      : []),
    ...(onRefresh
      ? [{
          key: "refresh",
          node: (
            <button className="ds-link is-quiet" onClick={onRefresh} disabled={refreshing} type="button">
              {refreshing ? "Atualizando..." : "Atualizar dados"}
            </button>
          ),
        }]
      : []),
  ];

  return (
    <div className="pageControls">
      <div className="pageControlsPeriod">
        <SegmentedControl
          ariaLabel="Período"
          value={periodPreset}
          onSelect={(id) => {
            // "Personalizado" só sinaliza o período em vigor; não é um atalho.
            if (id === "custom") return;
            onSelectPeriodPreset?.(id as "day" | "7d" | "30d" | "month");
          }}
          options={[
            ...PERIOD_OPTIONS,
            ...(periodPreset === "custom" ? [{ id: "custom", label: "Personalizado" }] : []),
          ]}
        />
        {periodPreset === "day" ? <DayPeriodControl /> : null}
      </div>

      <p className="pageControlsStatus">
        {statusParts.map((part, index) => (
          <Fragment key={part.key}>
            {index > 0 ? <span className="ds-metaSeparator" aria-hidden="true"> · </span> : null}
            {part.node}
          </Fragment>
        ))}
      </p>
    </div>
  );
}
