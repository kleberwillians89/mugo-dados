import { getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import GoalsPanel from "../components/goals/GoalsPanel";

/** Página Metas (rota /metas preservada). O conteúdo é o mesmo painel usado no Planejamento. */
export default function Goals({ canManage }: { canManage: boolean }) {
  return <Shell title="Metas" variant="editorial"><div className="ds-page goalsPage mugoBrand">
    <GoalsPanel canManage={canManage} header={(newButton) => <PageHeader company={getActiveClientName()} title="Metas" controls={newButton || undefined} />} />
  </div></Shell>;
}
