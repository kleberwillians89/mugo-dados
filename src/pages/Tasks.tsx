import { useEffect, useRef, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import { getCentral, type CentralView } from "../app/studio";
import { formatInteger } from "../app/dataFormat";
import { buildDashboardSummary } from "../app/centralSummary";
import PageHeader from "../components/data/PageHeader";
import ClientTasks from "../components/studio/ClientTasks";
import TaskBoard from "../components/studio/TaskBoard";
import "../styles/studio.css";

/** Indicadores operacionais da Central, agora exclusivos da página Tarefas. */
function TasksSummary() {
  const clientId = getActiveClientId();
  const [view, setView] = useState<CentralView | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const month = new Date();
    const monthKey = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`;
    void getCentral(monthKey).then((data) => {
      if (active && getActiveClientId() === clientId) setView(data);
    }).catch(() => {
      if (active) setView(null);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [clientId]);

  const summary = buildDashboardSummary(view);
  const cards = [
    { label: "Trabalhos em andamento", value: summary.inProgress, hint: "tarefas abertas" },
    { label: "Aguardando aprovação", value: summary.waitingApproval, hint: "revisão interna ou com o cliente" },
    { label: "Tarefas atrasadas", value: summary.overdue, hint: "prazos vencidos" },
    { label: "Trabalhos concluídos", value: summary.completed, hint: "" },
    { label: "Entregas no prazo", value: summary.onTime, hint: "", suffix: "%" },
  ];
  return <section className="centralSummary" aria-label="Resumo de tarefas">
    {cards.map((card) => <article className="centralSummaryCard" key={card.label}>
      <span>{card.label}</span>
      <strong>{loading || card.value == null ? "—" : `${formatInteger(card.value)}${card.suffix || ""}`}</strong>
      <small>{loading ? "Carregando…" : card.value == null ? "Dado não disponível nesta visão" : card.hint}</small>
    </article>)}
  </section>;
}

/** Tarefas da empresa ativa, em quadro, guardadas no Mugoverso. Quem gerencia cria, edita e move. */
export default function Tasks({ canManage = true, isAgency = true }: { canManage?: boolean; isAgency?: boolean }) {
  const refresh = useRef<() => void>(() => undefined);
  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Tarefas" controls={<button type="button" className="ds-button" onClick={() => refresh.current()}>Atualizar</button>} />
    <TasksSummary />
    <TaskBoard canManage={canManage} isAgency={isAgency} onRefreshRef={(fn) => { refresh.current = fn; }} />
  </div></Shell>;
}

/** Tarefas para o cliente (só leitura): as que a Mugô marcou como visíveis ao cliente, sem nada interno. */
export function ClientTasksPage() {
  const clientId = getActiveClientId();
  return <Shell title="Tarefas" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={getActiveClientName() || "empresa"} title="Tarefas" />
    <p className="libHint">O que está em andamento com a Mugô para a sua empresa.</p>
    <TasksSummary />
    <ClientTasks isAgency={false} clientId={clientId} standalone />
  </div></Shell>;
}
