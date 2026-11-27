import { useEffect, useState, type MouseEvent as ReactMouseEvent } from "react";
import { ArrowRight, ListChecks } from "lucide-react";
import { listMyTasks } from "../../app/myTasks";
import { getPathForRoute } from "../../app/routes";
import "../../styles/my-tasks.css";

/** Início: atalho em destaque para Minhas Tarefas, com quantas estão abertas (em todas as empresas). */
export default function MyTasksButton({ onOpen }: { onOpen: () => void }) {
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    listMyTasks().then((out) => { if (alive) setOpen(out.tasks.length); }).catch(() => { if (alive) setOpen(null); });
    return () => { alive = false; };
  }, []);
  function click(event: ReactMouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpen();
  }
  const count = open == null ? "" : open === 0 ? "nenhuma aberta" : `${open} aberta${open > 1 ? "s" : ""}`;
  return <a className="myTasksButton" href={getPathForRoute("my_tasks")} onClick={click}>
    <ListChecks size={18} aria-hidden="true" />
    Minhas Tarefas{count ? <small>— {count}</small> : null}
    <ArrowRight size={16} aria-hidden="true" />
  </a>;
}
