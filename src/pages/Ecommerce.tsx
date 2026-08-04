import { useEffect, useState } from "react";

import { listGenericConnections, type GenericConnection } from "../app/api";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getSelectedConnectionId } from "../app/connectionState";
import { usePeriod } from "../app/PeriodContext";
import FbitsSalesPanel from "../components/dashboard/FbitsSalesPanel";
import Shell from "../components/Shell";
import useDashboardFbits, { resolveCommerceConnection } from "../hooks/dashboard/useDashboardFbits";
import Shopify from "./Shopify";

type Props = {
  isAuthenticated: boolean;
  onLogout: () => void | Promise<void>;
  onOpenDashboard: () => void;
  onOpenGoogleReport: () => void;
};

function FbitsCommerce({ isAuthenticated, onLogout, onOpenDashboard }: Omit<Props, "onOpenGoogleReport">) {
  const { period } = usePeriod();
  const report = useDashboardFbits({
    isAuthenticated,
    activeClientId: getActiveClientId(),
    period,
  });
  return (
    <Shell
      themeClass="theme-client"
      title="E-commerce"
      subtitle={`Fonte principal: FBits · ${getActiveClientName()}`}
      right={
        <div className="shopifyShellActions">
          <button className="btn btnGhost" onClick={onOpenDashboard} type="button">Visão geral</button>
          <button className="btn btnPrimary" onClick={() => void report.reloadFbits({ force: true })} type="button">
            Atualizar dados
          </button>
          <button className="btnLogout" onClick={() => void onLogout()} type="button">Sair</button>
        </div>
      }
    >
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
  const [connection, setConnection] = useState<GenericConnection | null | undefined>(undefined);

  useEffect(() => {
    let active = true;
    listGenericConnections()
      .then((response) => {
        const clientId = getActiveClientId();
        const selectedId = getSelectedConnectionId(clientId, "shopify") ||
          getSelectedConnectionId(clientId, "fbits");
        if (active) setConnection(resolveCommerceConnection(response.connections, selectedId) as GenericConnection | null);
      })
      .catch(() => {
        if (active) setConnection(null);
      });
    return () => {
      active = false;
    };
  }, []);

  if (connection?.provider === "shopify") {
    return (
      <Shopify
        onLogout={props.onLogout}
        onOpenDashboard={props.onOpenDashboard}
        onOpenGoogleReport={props.onOpenGoogleReport}
      />
    );
  }
  if (connection?.provider === "fbits") {
    return <FbitsCommerce isAuthenticated={props.isAuthenticated} onLogout={props.onLogout} onOpenDashboard={props.onOpenDashboard} />;
  }
  return (
    <Shell
      themeClass="theme-client"
      title="E-commerce"
      subtitle={connection === undefined ? "Verificando a fonte principal…" : "Nenhuma fonte de comércio ativa"}
      right={<button className="btnLogout" onClick={() => void props.onLogout()} type="button">Sair</button>}
    >
      <section className="card cardWide">
        <div className="h1">{connection === undefined ? "Carregando e-commerce" : "Conecte Shopify ou FBits"}</div>
        <div className="p">Analytics e mídia paga permanecem independentes desta fonte.</div>
      </section>
    </Shell>
  );
}
