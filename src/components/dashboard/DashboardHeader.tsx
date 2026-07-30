type Props = {
  activeView: "meta" | "google";
  statusChips: Array<{
    label: string;
    connected?: boolean;
    refreshing?: boolean;
  }>;
  periodPreset: "7d" | "30d" | "month" | "custom";
  onSelectPeriodPreset?: (preset: "7d" | "30d" | "month") => void;
  refreshing?: boolean;
  backgroundRefreshing?: boolean;
  aiLoading?: boolean;
  onOpenMeta?: () => void;
  onOpenGoogleAnalytics?: () => void;
  onRefresh?: () => void;
  onAi?: () => void;
  onLogout: () => void | Promise<void>;
};

export default function DashboardHeader({
  activeView,
  statusChips,
  periodPreset,
  onSelectPeriodPreset,
  refreshing = false,
  backgroundRefreshing = false,
  aiLoading = false,
  onOpenMeta,
  onOpenGoogleAnalytics,
  onRefresh,
  onAi,
  onLogout,
}: Props) {
  return (
    <div className="dashHeader">
      <div className="dashHeaderSummary">
        <div className="dashHeaderStatusRow">
          {statusChips.map((chip) => (
            <span
              className={`dashHeaderStatusChip ${chip.connected ? "isConnected" : ""} ${chip.refreshing ? "isRefreshing" : ""}`.trim()}
              key={chip.label}
            >
              {chip.label}
            </span>
          ))}
          {backgroundRefreshing || refreshing ? (
            <span className="dashHeaderStatusChip isRefreshing">Atualizando em background</span>
          ) : null}
        </div>
      </div>

      <div className="dashHeaderMenu">
        <div className="dashHeaderFilters">
          <label className="dashHeaderField dashHeaderPeriod">
          <span className="dashHeaderPeriodLabel">Período</span>
          <select
            className="select"
            value={periodPreset}
            onChange={(event) => {
              const next = event.target.value as "7d" | "30d" | "month" | "custom";
              if (next === "custom") return;
              onSelectPeriodPreset?.(next);
            }}
            aria-label="Período"
          >
            <option value="7d">Últimos 7 dias</option>
            <option value="30d">Últimos 30 dias</option>
            <option value="month">Mês atual</option>
            {periodPreset === "custom" ? <option value="custom">Personalizado</option> : null}
          </select>
          </label>
        </div>

        <div className="dashHeaderActions">
          <button
            aria-current={activeView === "meta" ? "page" : undefined}
            className="btn btnGhost"
            onClick={onOpenMeta}
            type="button"
          >
            Dados Meta
          </button>
          {onOpenGoogleAnalytics ? (
            <button
              aria-current={activeView === "google" ? "page" : undefined}
              className="btn btnGhost"
              onClick={onOpenGoogleAnalytics}
              type="button"
            >
              Dados Google / FBits
            </button>
          ) : null}
          {onRefresh ? (
            <button className="btn btnPrimary" onClick={onRefresh} disabled={refreshing} type="button">
              {refreshing ? "Atualizando..." : "Atualizar dados"}
            </button>
          ) : null}
          {onAi ? (
            <button className="btn btnGold" onClick={onAi} disabled={aiLoading} type="button">
              {aiLoading ? "Analisando..." : "Análise IA"}
            </button>
          ) : null}
          <button className="btnLogout" onClick={() => onLogout()} type="button">
            Sair
          </button>
        </div>
      </div>
    </div>
  );
}
