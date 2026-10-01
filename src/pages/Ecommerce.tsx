import { useState, type ReactNode } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { syncFbitsConnection } from "../app/api";
import {
  isEcommerceSyncPending,
  resolveActiveEcommerceProvider,
  type EcommerceProvider,
} from "../app/ecommerceProvider";
import { usePeriod } from "../app/PeriodContext";
import type { ClientIntegrationConnection } from "../app/types";
import FbitsSalesPanel from "../components/dashboard/FbitsSalesPanel";
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
  const { period } = usePeriod();
  const report = useDashboardFbits({
    isAuthenticated,
    activeClientId: getActiveClientId(),
    period,
    provider: "fbits",
  });
  const [syncing, setSyncing] = useState(false);
  const [syncInfo, setSyncInfo] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const pending = isEcommerceSyncPending(connections);
  const lastError = connections.map((entry) => entry.last_error).find(Boolean) || null;

  async function syncNow() {
    setSyncing(true);
    setSyncError(null);
    try {
      // Endpoint por tenant: POST /api/clients/{empresa ativa}/fbits/sync.
      await syncFbitsConnection();
      setSyncInfo("Sincronização FBITS iniciada. Atualize os dados em alguns instantes.");
      await onConnectionsChanged();
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
      {pending ? (
        <section className="card cardWide" role="status" data-testid="ecommerce-fbits-pending">
          <div className="h1">FBITS conectado</div>
          <div className="p">Aguardando primeira sincronização. Os números aparecem assim que a importação terminar.</div>
        </section>
      ) : null}
      {lastError ? <div className="pill pillDanger" role="alert">{lastError}</div> : null}
      {syncInfo ? <div className="smallMuted" role="status">{syncInfo}</div> : null}
      {syncError ? <div className="pill pillDanger" role="alert">{syncError}</div> : null}
      <FbitsSalesPanel
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
