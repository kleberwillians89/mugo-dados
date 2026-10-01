import { useMemo, useState, type ReactNode } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { syncFbitsConnection } from "../app/api";
import {
  isEcommerceSyncPending,
  resolveActiveEcommerceProvider,
  type EcommerceProvider,
} from "../app/ecommerceProvider";
import { usePeriod } from "../app/PeriodContext";
import type { ClientIntegrationConnection } from "../app/types";
import FbitsExecutiveDashboard from "../components/dashboard/FbitsExecutiveDashboard";
import Shell from "../components/Shell";
import useActiveEcommerceProvider from "../hooks/dashboard/useActiveEcommerceProvider";
import useDashboardFbits from "../hooks/dashboard/useDashboardFbits";
import Shopify from "./Shopify";

type Props = {
  isAuthenticated: boolean;
  onLogout: () => void | Promise<void>;
  onOpenDashboard: () => void;
  onOpenGoogleReport: () => void;
  onOpenIntegrations?: () => void;
};

const PROVIDER_LABEL: Record<EcommerceProvider, string> = { shopify: "Shopify", fbits: "FBITS" };

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

function endingTodayPeriod(days: number) {
  const end = todayInSaoPaulo();
  const endDate = new Date(`${end}T00:00:00Z`);
  endDate.setUTCDate(endDate.getUTCDate() - Math.max(1, days) + 1);
  return { start: endDate.toISOString().slice(0, 10), end };
}

function EcommerceShell({ onLogout, children }: { onLogout: Props["onLogout"]; children: ReactNode }) {
  return (
    <Shell
      themeClass="theme-client"
      title="E-commerce"
      subtitle={getActiveClientName()}
      right={<button className="btnLogout" onClick={() => void onLogout()} type="button">Sair</button>}
    >
      <section className="card cardWide">{children}</section>
    </Shell>
  );
}

type FbitsCommerceProps = Omit<Props, "onOpenGoogleReport"> & {
  connections: ClientIntegrationConnection[];
  onConnectionsChanged: () => void | Promise<void>;
};

function FbitsCommerce({ isAuthenticated, onLogout, onOpenDashboard, connections, onConnectionsChanged }: FbitsCommerceProps) {
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
  const lastSyncAt = useMemo(
    () => connections.map((entry) => entry.last_successful_sync_at || entry.last_sync_at).find(Boolean) || report.fbitsData?.last_sync_at || null,
    [connections, report.fbitsData?.last_sync_at]
  );

  function previousMonth() {
    const today = new Date(`${todayInSaoPaulo()}T12:00:00`);
    const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const end = new Date(today.getFullYear(), today.getMonth(), 0);
    const asInput = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
    setPeriod({ start: asInput(start), end: asInput(end) });
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
    <Shell
      themeClass="theme-client"
      title="E-commerce"
      subtitle={`Fonte: FBITS · ${getActiveClientName()}`}
      right={
        <div className="shopifyShellActions">
          <button className="btn btnGhost" onClick={onOpenDashboard} type="button">Meta</button>
          <button className="btn btnGhost" disabled={syncing} onClick={() => void syncNow()} type="button">
            {syncing ? "Sincronizando..." : "Sincronizar agora"}
          </button>
          <button className="btn btnPrimary" onClick={() => void report.reloadFbits({ force: true })} type="button">
            Atualizar dados
          </button>
          <button className="btnLogout" onClick={() => void onLogout()} type="button">Sair</button>
        </div>
      }
    >
      <section className="fbitsExecutiveHeader" aria-label="Período do dashboard FBITS">
        <div>
          <div className="fbitsEyebrow">FBITS / Wake Commerce</div>
          <div className="h1">Visão executiva de vendas</div>
          <div className="smallMuted">
            {lastSyncAt ? `Sincronizado em ${new Date(lastSyncAt).toLocaleString("pt-BR")}` : "Conectado sem sincronização concluída"}
          </div>
        </div>
        <div className="fbitsPeriodPicker">
          <div className="fbitsPeriodPresets">
            <button className="btn btnGhost" type="button" onClick={() => setPeriod(endingTodayPeriod(1))}>Hoje</button>
            <button className="btn btnGhost" type="button" onClick={() => setPeriod(endingTodayPeriod(7))}>7 dias</button>
            <button className="btn btnGhost" type="button" onClick={() => setPeriod(endingTodayPeriod(30))}>30 dias</button>
            <button className="btn btnGhost" type="button" onClick={() => setPeriod({ start: `${todayInSaoPaulo().slice(0, 7)}-01`, end: todayInSaoPaulo() })}>Este mês</button>
            <button className="btn btnGhost" type="button" onClick={previousMonth}>Mês passado</button>
            <button className="btn btnGhost" type="button" aria-expanded={showCustom} onClick={() => setShowCustom((value) => !value)}>Personalizado</button>
          </div>
          {showCustom ? (
            <div className="fbitsCustomPeriod">
              <label><span>Data inicial</span><input type="date" value={customStart} onChange={(event) => setCustomStart(event.target.value)} /></label>
              <label><span>Data final</span><input type="date" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} /></label>
              <button className="btn btnPrimary" type="button" disabled={!customStart || !customEnd || customStart > customEnd} onClick={applyCustomPeriod}>Aplicar</button>
            </div>
          ) : null}
        </div>
      </section>
      {pending ? (
        <section className="card cardWide" role="status" data-testid="ecommerce-fbits-pending">
          <div className="h1">FBITS conectado</div>
          <div className="p">Aguardando primeira sincronização. Os números aparecem assim que a importação terminar.</div>
        </section>
      ) : null}
      {lastError ? <div className="pill pillDanger" role="alert">{lastError}</div> : null}
      {syncInfo ? <div className="smallMuted" role="status">{syncInfo}</div> : null}
      {syncError ? <div className="pill pillDanger" role="alert">{syncError}</div> : null}
      <FbitsExecutiveDashboard
        data={report.fbitsData}
        orders={report.fbitsOrders}
        loading={report.loadingFbits}
        error={report.fbitsError}
      />
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
    return <EcommerceShell onLogout={props.onLogout}><div className="p" role="status">Identificando a integração de e-commerce...</div></EcommerceShell>;
  }
  if (integrations.error) {
    return (
      <EcommerceShell onLogout={props.onLogout}>
        <div className="pill pillDanger" role="alert">{integrations.error}</div>
        <button className="btn btnGhost" type="button" onClick={() => void integrations.reload()}>Tentar novamente</button>
      </EcommerceShell>
    );
  }

  const resolution = resolveActiveEcommerceProvider(integrations.connections, chosen);
  if (resolution.state === "none") {
    return (
      <EcommerceShell onLogout={props.onLogout}>
        <div className="h1">Nenhuma integração de Ecommerce conectada</div>
        <div className="p">Conecte Shopify ou FBITS para ver os dados de vendas desta empresa.</div>
        {props.onOpenIntegrations ? (
          <button className="btn btnPrimary" type="button" onClick={props.onOpenIntegrations}>Ir para Integrações</button>
        ) : null}
      </EcommerceShell>
    );
  }
  if (resolution.state === "ambiguous") {
    return (
      <EcommerceShell onLogout={props.onLogout}>
        <div className="h1">Mais de uma integração de Ecommerce está conectada</div>
        <div className="p">Escolha qual fonte deve alimentar os números desta página.</div>
        <div className="shopifyShellActions">
          {resolution.candidates.map((provider) => (
            <button key={provider} className="btn btnGhost" type="button" onClick={() => setChosen(provider)}>
              Usar {PROVIDER_LABEL[provider]}
            </button>
          ))}
        </div>
      </EcommerceShell>
    );
  }
  if (resolution.provider === "fbits") {
    return (
      <FbitsCommerce
        isAuthenticated={props.isAuthenticated}
        onLogout={props.onLogout}
        onOpenDashboard={props.onOpenDashboard}
        connections={resolution.connections}
        onConnectionsChanged={integrations.refresh}
      />
    );
  }
  return (
    <Shopify
      onLogout={props.onLogout}
      onOpenDashboard={props.onOpenDashboard}
      onOpenGoogleReport={props.onOpenGoogleReport}
    />
  );
}
