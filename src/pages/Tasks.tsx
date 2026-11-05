import { useRef } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import ClientTasks from "../components/studio/ClientTasks";
import TaskBoard from "../components/studio/TaskBoard";
import "../styles/studio.css";

export { sortTasks } from "../components/studio/TaskBoard";

/** Tarefas da agência para a empresa ativa, em quadro, lidas do CRM Mugô. Financeiro fica de fora. */
export default function Tasks() {
  const refresh = useRef<() => void>(() => undefined);
  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Tarefas da agência" controls={<button type="button" className="ds-button" onClick={() => refresh.current()}>Atualizar</button>} />
    <TaskBoard onRefreshRef={(fn) => { refresh.current = fn; }} />
  </div></Shell>;
}

/** Tarefas para o cliente: só o que a Mugô marcou com a etiqueta "cliente" no CRM, sem nada interno. */
export function ClientTasksPage() {
  const clientId = getActiveClientId();
  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Tarefas" />
    <p className="libHint">O que está em andamento com a Mugô para a sua empresa.</p>
    <ClientTasks isAgency={false} clientId={clientId} standalone />
  </div></Shell>;
}
