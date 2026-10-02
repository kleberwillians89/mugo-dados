import { useMemo, useState, type ReactNode } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { syncFbitsConnection } from "../app/api";
import { formatCalendarRange, formatDateTimeSaoPaulo } from "../app/dataFormat";
import {
  isEcommerceSyncPending,
  resolveActiveEcommerceProvider,
  type EcommerceProvider,
} from "../app/ecommerceProvider";
import { usePeriod } from "../app/PeriodContext";
import type { ClientIntegrationConnection } from "../app/types";
import FbitsExecutiveDashboard from "../components/dashboard/FbitsExecutiveDashboard";
import DataNotice from "../components/data/DataNotice";
import PageHeader from "../components/data/PageHeader";
import SegmentedControl from "../components/data/SegmentedControl";
import Shell from "../components/Shell";
import useActiveEcommerceProvider from "../hooks/dashboard/useActiveEcommerceProvider";
import useDashboardFbits from "../hooks/dashboard/useDashboardFbits";
import Shopify from "./Shopify";

type Props = {
  isAuthenticated: boolean;
  /**
   * Mesmos papéis que o backend aceita no sync (require_client_role):
   * platform/agency admin e client_admin (owner/admin legados). Viewer não
   * recebe a ação — o backend responderia 403.
   */
  canSync: boolean;
  onLogout: () => void | Promise<void>;
  onOpenDashboard: () => void;
  onOpenGoogleReport: () => void;
  onOpenIntegrations?: () => void;
};

const PROVIDER_LABEL: Record<EcommerceProvider, string> = { shopify: "Shopify", fbits: "FBITS" };

type PeriodRange = { start: string; end: string };

function todayInSaoPaulo(): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function endingTodayPeriod(days: number): PeriodRange {
  const end = todayInSaoPaulo();
  const endDate = new Date(`${end}T00:00:00Z`);
  endDate.setUTCDate(endDate.getUTCDate() - Math.max(1, days) + 1);
  return { start: endDate.toISOString().slice(0, 10), end };
}

function currentMonthPeriod(): PeriodRange {
  return { start: `${todayInSaoPaulo().slice(0, 7)}-01`, end: todayInSaoPaulo() };
}

function previousMonthPeriod(): PeriodRange {
  const today = new Date(`${todayInSaoPaulo()}T12:00:00`);
  const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const end = new Date(today.getFullYear(), today.getMonth(), 0);
  const asInput = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  return { start: asInput(start), end: asInput(end) };
}

const PERIOD_PRESETS: Array<{ id: string; label: string; range: () => PeriodRange }> = [
  { id: "today", label: "Hoje", range: () => endingTodayPeriod(1) },
  { id: "7d", label: "7 dias", range: () => endingTodayPeriod(7) },
  { id: "30d", label: "30 dias", range: () => endingTodayPeriod(30) },
  { id: "month", label: "Este mês", range: currentMonthPeriod },
  { id: "previous-month", label: "Mês passado", range: previousMonthPeriod },
];

/** Qual atalho corresponde ao período em vigor — só para destacar o ativo. */
function activePresetId(period: PeriodRange): string | null {
  const match = PERIOD_PRESETS.find((preset) => {
    const range = preset.range();
    return range.start === period.start && range.end === period.end;
  });
  return match ? match.id : null;
}

// Marca da empresa, navegação e "Sair" vivem na sidebar global (mesmo onLogout do App).
function EcommerceShell({ children }: { children: ReactNode }) {
  return (
    <Shell variant="editorial" themeClass="theme-editorial" title="Ecommerce">
      <div className="ds-page">
        <PageHeader company={getActiveClientName()} title="Ecommerce" />
        <div className="ds-group">{children}</div>
      </div>
    </Shell>
  );
}

type FbitsCommerceProps = Omit<Props, "onOpenGoogleReport"> & {
  connections: ClientIntegrationConnection[];
  onConnectionsChanged: () => void | Promise<void>;
};

function FbitsCommerce({ isAuthenticated, canSync, connections, onConnectionsChanged }: FbitsCommerceProps) {
  const { period, setPeriod } = usePeriod();
  const report = useDashboardFbits({
    isAuthenticated,
    activeClientId: getActiveClientId(),
    period,
    provider: "fbits",
  });
  const [syncing, setSyncing] = useState(false);
  const [syncInfo, setSyncInfo] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [customStart, setCustomStart] = useState(period.start);
  const [customEnd, setCustomEnd] = useState(period.end);
  const [showCustom, setShowCustom] = useState(false);
  const pending = isEcommerceSyncPending(connections);
  const lastError = connections.map((entry) => entry.last_error).find(Boolean) || null;
  // Dado já visível (último válido): não há "primeira importação pendente".
  const hasCommerceData = Number(report.fbitsData?.summary?.pedidos || 0) > 0
    || Number(report.fbitsData?.summary?.receita_oficial || 0) > 0;
  const lastSyncAt = useMemo(
    () => connections.map((entry) => entry.last_successful_sync_at || entry.last_sync_at).find(Boolean) || report.fbitsData?.last_sync_at || null,
    [connections, report.fbitsData?.last_sync_at]
  );
  const activePreset = activePresetId(period);

  function selectPeriod(id: string) {
    if (id === "custom") {
      setShowCustom((value) => !value);
      return;
    }
    // Atalho escolhido: as datas do personalizado saem de cena (mesmo período de antes).
    setShowCustom(false);
    const preset = PERIOD_PRESETS.find((item) => item.id === id);
    if (preset) setPeriod(preset.range());
  }

  function applyCustomPeriod() {
    if (!customStart || !customEnd || customStart > customEnd) return;
    setPeriod({ start: customStart, end: customEnd });
  }

  async function syncNow() {
    setSyncing(true);
    setSyncError(null);
    try {
      // Endpoint por tenant: POST /api/clients/{empresa ativa}/fbits/sync.
      await syncFbitsConnection();
      setSyncInfo("Sincronização FBITS iniciada. Atualize os dados em alguns instantes.");
      await onConnectionsChanged();
      report.invalidateFbitsCache();
      await report.reloadFbits({ force: true });
    } catch (cause) {
      setSyncError(cause instanceof Error && cause.message ? cause.message : "Não foi possível iniciar a sincronização FBITS.");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <Shell variant="editorial" themeClass="theme-editorial" title="Ecommerce">
      <div className="ds-page">
        <div className="ds-group">
          <PageHeader
            company={getActiveClientName()}
            title="Ecommerce"
            dateline={
              <>
                <span className="ds-datelineSource" data-testid="ecommerce-source">FBITS</span>
                {/* Com números na tela, anunciar "sem sincronização" seria
                    contraditório: os KPIs oficiais da FBITS não dependem de
                    sync. Sem data e sem dado, o aviso continua. */}
                <span>
                  {lastSyncAt
                    ? `Sincronizado em ${formatDateTimeSaoPaulo(lastSyncAt)}`
                    : hasCommerceData ? "" : "Sem sincronização concluída"}
                </span>
                {canSync ? (
                  <span>
                    <button className="ds-link is-quiet" disabled={syncing} onClick={() => void syncNow()} type="button">
                      {syncing ? "Sincronizando..." : "Sincronizar agora"}
                    </button>
                  </span>
                ) : null}
                {canSync ? (
                  <span>
                    <button className="ds-link is-quiet" onClick={() => void report.reloadFbits({ force: true })} type="button">
                      Atualizar dados
                    </button>
                  </span>
                ) : null}
              </>
            }
            controls={
              <SegmentedControl
                ariaLabel="Período"
                value={showCustom ? "custom" : activePreset ?? "custom"}
                onSelect={selectPeriod}
                options={[
                  ...PERIOD_PRESETS.map(({ id, label }) => ({ id, label })),
                  { id: "custom", label: "Personalizado", expanded: showCustom },
                ]}
              />
            }
            panel={showCustom ? (
              <div className="ds-customPeriod">
                <label className="ds-field"><span>Data inicial</span><input type="date" value={customStart} onChange={(event) => setCustomStart(event.target.value)} /></label>
                <label className="ds-field"><span>Data final</span><input type="date" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} /></label>
                <button className="ds-button is-primary" type="button" disabled={!customStart || !customEnd || customStart > customEnd} onClick={applyCustomPeriod}>Aplicar</button>
              </div>
            ) : null}
            controlsNote={formatCalendarRange(period.start, period.end)}
          />
          {/* Com dado na tela não existe "primeira sincronização pendente":
              os KPIs oficiais vêm da FBITS e o analítico mantém a última
              leitura válida. */}
          {pending && !hasCommerceData ? (
            <DataNotice role="status" testId="ecommerce-fbits-pending" title="FBITS conectado">
              Ainda não há dados para este período.
            </DataNotice>
          ) : null}
          {/* Detalhe de atualização é operacional: só para quem pode agir. */}
          {lastError && canSync ? (
            <DataNotice
              tone={hasCommerceData ? "warning" : "negative"}
              role="status"
              testId="ecommerce-fbits-sync-warning"
              title={hasCommerceData ? "Atualização automática pendente" : "Não foi possível atualizar"}
            >
              {hasCommerceData
                ? "Os números seguem válidos. Verifique a conexão em Integrações para retomar as atualizações automáticas."
                : lastError}
            </DataNotice>
          ) : null}
          {syncInfo ? <p className="ds-status" role="status">{syncInfo}</p> : null}
          {syncError ? <DataNotice tone="negative" role="alert" title="Sincronização não iniciada">{syncError}</DataNotice> : null}
        </div>
        <FbitsExecutiveDashboard
          data={report.fbitsData}
          orders={report.fbitsOrders}
          loading={report.loadingFbits}
          error={report.fbitsError}
          syncPending={pending && !hasCommerceData}
        />
      </div>
    </Shell>
  );
}

export default function Ecommerce(props: Props) {
  // App remonta esta página por empresa (key=ecommerce:<tenant>); o hook
  // ainda descarta respostas que não sejam do tenant ativo.
  const activeClientId = getActiveClientId();
  const integrations = useActiveEcommerceProvider(activeClientId);
  // Escolha explícita só vale nesta visita e nesta empresa; sem schema novo.
  const [chosen, setChosen] = useState<EcommerceProvider | null>(null);

  if (integrations.loading) {
    return (
      <EcommerceShell>
        <p className="ds-status" role="status">Identificando a integração de e-commerce...</p>
      </EcommerceShell>
    );
  }
  if (integrations.error) {
    return (
      <EcommerceShell>
        <DataNotice
          tone="negative"
          role="alert"
          title="Não foi possível verificar as integrações"
          actions={<button className="ds-button" type="button" onClick={() => void integrations.reload()}>Tentar novamente</button>}
        >
          {integrations.error}
        </DataNotice>
      </EcommerceShell>
    );
  }

  const resolution = resolveActiveEcommerceProvider(integrations.connections, chosen);
  if (resolution.state === "none") {
    return (
      <EcommerceShell>
        <DataNotice
          title="Nenhuma integração de Ecommerce conectada"
          actions={props.onOpenIntegrations ? (
            <button className="ds-button is-primary" type="button" onClick={props.onOpenIntegrations}>Ir para Integrações</button>
          ) : null}
        >
          {props.onOpenIntegrations
            ? "Conecte Shopify ou FBITS para ver os dados de vendas desta empresa."
            : "Os dados de vendas aparecem aqui quando a empresa conectar Shopify ou FBITS."}
        </DataNotice>
      </EcommerceShell>
    );
  }
  if (resolution.state === "ambiguous") {
    return (
      <EcommerceShell>
        <DataNotice
          tone="warning"
          title="Mais de uma integração de Ecommerce está conectada"
          actions={resolution.candidates.map((provider) => (
            <button key={provider} className="ds-button" type="button" onClick={() => setChosen(provider)}>
              Usar {PROVIDER_LABEL[provider]}
            </button>
          ))}
        >
          Escolha qual fonte deve alimentar os números desta página.
        </DataNotice>
      </EcommerceShell>
    );
  }
  if (resolution.provider === "fbits") {
    return (
      <FbitsCommerce
        isAuthenticated={props.isAuthenticated}
        canSync={props.canSync}
        onLogout={props.onLogout}
        onOpenDashboard={props.onOpenDashboard}
        connections={resolution.connections}
        onConnectionsChanged={integrations.refresh}
      />
    );
  }
  return (
    <Shopify
      canSync={props.canSync}
      onLogout={props.onLogout}
      onOpenDashboard={props.onOpenDashboard}
      onOpenGoogleReport={props.onOpenGoogleReport}
    />
  );
}
