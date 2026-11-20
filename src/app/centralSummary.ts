import type { CentralView } from "./studio";

export type DashboardSummary = {
  inProgress: number | null;
  waitingApproval: number | null;
  overdue: number | null;
  completed: number | null;
  onTime: number | null;
};

/** Só transforma contagens já existentes; ausência de dado nunca vira zero. */
export function buildDashboardSummary(view: CentralView | null): DashboardSummary {
  const tasksAvailable = Boolean(view?.tasks?.available);
  const counts = view?.calendar?.counts;
  return {
    inProgress: tasksAvailable && typeof view?.tasks?.open === "number" ? view.tasks.open : null,
    waitingApproval: counts ? (counts.revisao_interna ?? 0) + (counts.com_cliente ?? 0) : null,
    overdue: tasksAvailable && typeof view?.tasks?.late === "number" ? view.tasks.late : null,
    // O contrato atual da Central não fornece concluídas nem cumprimento de prazo.
    completed: null,
    onTime: null,
  };
}

export function isCurrentClientRequest(requestClientId: string | null, currentClientId: string | null) {
  return Boolean(requestClientId && requestClientId === currentClientId);
}
