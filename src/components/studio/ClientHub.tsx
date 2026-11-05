import { useCallback, useEffect, useState } from "react";
import { CheckSquare, ChevronDown, ClipboardCheck, MessageCircle, Sparkles, Users } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../../app/activeClient";
import { chatUnread, type ChatChannel } from "../../app/studio";
import Approval from "../../pages/Approval";
import BrandChat from "./BrandChat";
import BrandKnowledge from "./BrandKnowledge";
import BrandTimeline from "./BrandTimeline";
import ClientTasks from "./ClientTasks";
import TaskBoard from "./TaskBoard";

/** 5 seções no máximo; cada uma com no máximo 2 visões. Antes eram 9 abas soltas. */
type Section = "conversa" | "tarefas" | "aprovacoes" | "ia" | "contatos";
type View = "cliente" | "equipe" | "pedidos" | "linha" | "conhecimento" | "referencias" | "pessoas" | "whatsapp" | "board";
type SectionDef = { id: Section; label: string; hint: string; icon: typeof MessageCircle; views?: { id: View; label: string }[] };
const STORE = "mugo.calendar.hub.v2";

function sections(team: boolean): SectionDef[] {
  return [
    { id: "conversa", label: "Conversa", hint: team ? "Fale com o cliente ou só com a equipe" : "Fale com a equipe Mugô", icon: MessageCircle,
      views: team ? [{ id: "cliente", label: "Com o cliente" }, { id: "equipe", label: "Só equipe" }] : undefined },
    { id: "tarefas", label: "Tarefas", hint: "O que está em andamento", icon: CheckSquare },
    { id: "aprovacoes", label: "Aprovações", hint: "Pedidos enviados e histórico", icon: ClipboardCheck,
      views: [{ id: "pedidos", label: "Pedidos" }, { id: "linha", label: "Linha do tempo" }] },
    { id: "ia", label: "Marca & IA", hint: "O que a IA sabe e as referências", icon: Sparkles,
      views: [{ id: "conhecimento", label: "Conhecimento" }, { id: "referencias", label: "Referências" }] },
    ...(team ? [{ id: "contatos" as const, label: "Contatos", hint: "Quem recebe e o WhatsApp", icon: Users,
      views: [{ id: "pessoas" as const, label: "Pessoas" }, { id: "whatsapp" as const, label: "WhatsApp" }] }] : []),
  ];
}

type Memory = { open: boolean; section: Section; views: Partial<Record<Section, View>> };
function remembered(): Memory {
  try {
    const v = JSON.parse(window.localStorage.getItem(STORE) || "{}");
    return { open: v.open !== false, section: v.section || "conversa", views: v.views || {} };
  } catch { return { open: true, section: "conversa", views: {} }; }
}

/**
 * Central do cliente no Calendário: conversa, tarefas, aprovações, marca & IA e contatos.
 * Navegação lateral com ícones (no celular vira uma faixa rolável) e, dentro de cada seção, no máximo duas visões.
 */
export default function ClientHub({ team, canManage, isAgency, month, posts, onOpenItem, onChanged }: {
  team: boolean; canManage: boolean; isAgency: boolean; month: string;
  posts: { id: string; title: string }[]; onOpenItem: (id: string) => void; onChanged: () => void;
}) {
  const clientId = getActiveClientId();
  const brand = getActiveClientName() || "Cliente";
  const list = sections(team);
  const [memory, setMemory] = useState(remembered);
  const current = list.find((s) => s.id === memory.section) || list[0];
  const view: View | undefined = current.views ? (current.views.find((v) => v.id === memory.views[current.id])?.id || current.views[0].id) : undefined;
  const [unread, setUnread] = useState<Partial<Record<ChatChannel, number>>>({});

  const save = (next: Memory) => {
    setMemory(next);
    try { window.localStorage.setItem(STORE, JSON.stringify(next)); } catch { /* sem armazenamento: só não lembra */ }
  };
  const refreshUnread = useCallback(() => { chatUnread().then((r) => setUnread(r.unread || {})).catch(() => undefined); }, []);
  useEffect(() => { refreshUnread(); const t = window.setInterval(refreshUnread, 60000); return () => window.clearInterval(t); }, [refreshUnread, clientId]);
  const markRead = useCallback(() => { window.setTimeout(refreshUnread, 300); }, [refreshUnread]);

  const badge = (id: Section | View): number => {
    if (id === "conversa") return (unread.cliente || 0) + (team ? unread.equipe || 0 : 0);
    if (id === "cliente") return unread.cliente || 0;
    if (id === "equipe") return unread.equipe || 0;
    return 0;
  };
  const total = badge("conversa");
  const embed = (tab: "pedidos" | "referencias" | "contatos" | "mensagens") =>
    <Approval key={`${tab}-${clientId}`} embedded month={month} tabs={[tab]} canManage={canManage} isAgency={isAgency} onChanged={onChanged} />;

  return <section className={`hub${memory.open ? " is-open" : ""}`} aria-label="Central do cliente">
    <button type="button" className="hubHead" aria-expanded={memory.open} onClick={() => save({ ...memory, open: !memory.open })}>
      <span className="hubAvatar" aria-hidden="true">{brand.slice(0, 1).toUpperCase()}</span>
      <span className="hubTitle"><b>{team ? `Central do cliente · ${brand}` : "Com a Mugô"}</b>
        <small>{memory.open ? current.hint : "Conversa, tarefas, aprovações e o que a IA sabe da marca"}</small></span>
      {total && !memory.open ? <i className="hubBadge">{total}</i> : null}
      <ChevronDown className="hubChevron" size={18} aria-hidden="true" />
    </button>
    {memory.open ? <div className="hubLayout">
      <nav className="hubNav" aria-label="Seções">
        {list.map((s) => {
          const Icon = s.icon;
          const n = badge(s.id);
          return <button key={s.id} type="button" className={s.id === current.id ? "is-active" : ""} aria-current={s.id === current.id ? "page" : undefined}
            onClick={() => save({ ...memory, section: s.id })}>
            <Icon size={17} aria-hidden="true" /><span>{s.label}</span>{n ? <i className="hubBadge">{n}</i> : null}
          </button>;
        })}
      </nav>
      <div className="hubBody">
        {current.views ? <div className="hubViews" role="tablist" aria-label={current.label}>
          {current.views.map((v) => <button key={v.id} type="button" role="tab" aria-selected={view === v.id} className={view === v.id ? "is-active" : ""}
            onClick={() => save({ ...memory, views: { ...memory.views, [current.id]: v.id } })}>
            {v.label}{badge(v.id) ? <i className="hubBadge">{badge(v.id)}</i> : null}
          </button>)}
        </div> : null}
        {current.id === "conversa" ? <BrandChat key={`${view || "cliente"}-${clientId}`} channel={view === "equipe" && team ? "equipe" : "cliente"}
          posts={posts} onOpenItem={onOpenItem} onRead={markRead} /> : null}
        {current.id === "tarefas" ? (team ? <TaskBoard key={clientId} /> : <ClientTasks isAgency={false} clientId={clientId} standalone />) : null}
        {current.id === "aprovacoes" ? (view === "linha" ? <BrandTimeline key={clientId} onOpenItem={onOpenItem} /> : embed("pedidos")) : null}
        {current.id === "ia" ? (view === "referencias" ? embed("referencias") : <BrandKnowledge key={clientId} canManage={canManage} />) : null}
        {current.id === "contatos" && team ? (view === "whatsapp" ? embed("mensagens") : embed("contatos")) : null}
      </div>
    </div> : null}
  </section>;
}

