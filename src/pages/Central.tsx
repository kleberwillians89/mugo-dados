import { useCallback, useEffect, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getCentral, type CentralView } from "../app/studio";
import { isCurrentClientRequest } from "../app/centralSummary";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import AiUsageButton from "../components/studio/AiUsageButton";
import ClientExecutivePanel from "../components/dashboard/ClientExecutivePanel";
import PageSkeleton from "../components/data/PageSkeleton";
import "../styles/studio.css";
import "../styles/clientExecutive.css";

const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m: string, n: number) => { const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5)) - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

/** Dashboard gerencial: uma única leitura por tenant/período, sem geração automática. */
export default function Central({ isAgency = false }: { isAgency?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [month, setMonth] = useState(thisMonth);
  const [view, setView] = useState<CentralView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const requestClientId = getActiveClientId();
    setLoading(true); setError(null); setView(null);
    try {
      const data = await getCentral(month);
      if (!isCurrentClientRequest(requestClientId, getActiveClientId())) return;
      setView(data);
    } catch (cause) {
      if (!isCurrentClientRequest(requestClientId, getActiveClientId())) return;
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível carregar o Dashboard.");
    } finally {
      if (isCurrentClientRequest(requestClientId, getActiveClientId())) setLoading(false);
    }
  }, [month, clientId]);
  useEffect(() => { void load(); }, [load]);

  const today = new Date().toISOString().slice(0, 10);
  const healthStart = `${month}-01`;
  const monthEnd = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).toISOString().slice(0, 10);
  const healthEnd = view?.numbers?.end || (monthEnd < today ? monthEnd : today);

  return <Shell title="Dashboard" variant="editorial"><div className="ds-page studioPage clientDashboardPage">
    <PageHeader company={clientName} title="Dashboard" dateline="Desempenho da marca, resultados e operação em uma única visão." controls={<div className="calNav dashboardHeaderControls">
      <button type="button" className="ds-button" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
      <h2 className="calRange">{MONTH_NAMES[Number(month.slice(5)) - 1]} {month.slice(0, 4)}</h2>
      <button type="button" className="ds-button" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
      <AiUsageButton clientName={clientName} isAgency={isAgency} />
    </div>} />
    {error ? <div className="dashboardLoadError" role="alert"><p>{error}</p><button type="button" className="ds-button" onClick={() => void load()}>Tentar novamente</button></div> : null}
    {loading ? <PageSkeleton label="Montando o Dashboard com os dados disponíveis…" /> : null}
    {!loading && view ? <ClientExecutivePanel view={view} month={month} clientName={clientName} healthStart={healthStart} healthEnd={healthEnd} showHealth={healthStart <= today} /> : null}
  </div></Shell>;
}
