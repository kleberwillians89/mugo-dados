import { useDashboardSnapshot } from "../app/DashboardDataContext";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { usePeriod } from "../app/PeriodContext";
import FbitsSalesPanel from "../components/dashboard/FbitsSalesPanel";
import Shell from "../components/Shell";
import useDashboardFbits from "../hooks/dashboard/useDashboardFbits";
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
          <button className="btn btnGhost" onClick={onOpenDashboard} type="button">Meta</button>
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
  const model = useDashboardSnapshot();
  if (model.sources.some((source) => source.provider === "fbits")) {
    return <FbitsCommerce isAuthenticated={props.isAuthenticated} onLogout={props.onLogout} onOpenDashboard={props.onOpenDashboard} />;
  }
  return (
    <Shopify
      onLogout={props.onLogout}
      onOpenDashboard={props.onOpenDashboard}
      onOpenGoogleReport={props.onOpenGoogleReport}
    />
  );
}
