import { useRef } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import ClientTasks from "../components/studio/ClientTasks";
import TaskBoard from "../components/studio/TaskBoard";
import "../styles/studio.css";

export { sortTasks } from "../components/studio/TaskBoard";

/** Tarefas da empresa ativa, em quadro, guardadas no Mugoverso. Quem gerencia cria, edita e move. */
export default function Tasks({ canManage = true, isAgency = true }: { canManage?: boolean; isAgency?: boolean }) {
  const refresh = useRef<() => void>(() => undefined);
  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Tarefas" controls={<button type="button" className="ds-button" onClick={() => refresh.current()}>Atualizar</button>} />
    <TaskBoard canManage={canManage} isAgency={isAgency} onRefreshRef={(fn) => { refresh.current = fn; }} />
  </div></Shell>;
}

/** Tarefas para o cliente (só leitura): as que a Mugô marcou como visíveis ao cliente, sem nada interno. */
export function ClientTasksPage() {
  const clientId = getActiveClientId();
  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Tarefas" />
    <p className="libHint">O que está em andamento com a Mugô para a sua empresa.</p>
    <ClientTasks isAgency={false} clientId={clientId} standalone />
  </div></Shell>;
}
