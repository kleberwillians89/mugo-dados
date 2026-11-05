import { useCallback, useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { chatUnread, type ChatChannel } from "../../app/studio";
import Approval from "../../pages/Approval";
import BrandChat from "./BrandChat";
import BrandKnowledge from "./BrandKnowledge";
import BrandTimeline from "./BrandTimeline";
import ClientTasks from "./ClientTasks";
import TaskBoard from "./TaskBoard";

type HubTab = "conversa" | "equipe" | "tarefas" | "conhecimento" | "linha" | "pedidos" | "referencias" | "contatos" | "mensagens";
const LABELS: Record<HubTab, string> = { conversa: "Conversa", equipe: "Equipe (interno)", tarefas: "Tarefas", conhecimento: "Conhecimento da IA", linha: "Linha do tempo",
  pedidos: "Pedidos de aprovação", referencias: "Referências", contatos: "Contatos", mensagens: "WhatsApp" };
const STORE = "mugo.calendar.hub";

function remembered(): { open: boolean; tab: HubTab | null } {
  try { const v = JSON.parse(window.localStorage.getItem(STORE) || "{}"); return { open: v.open !== false, tab: v.tab || null }; }
  catch { return { open: true, tab: null }; }
}

/**
 * Painel do cliente aberto na própria página do Calendário (antes ficava atrás de um botão):
 * conversa, tarefas, linha do tempo, pedidos e referências — e, para a equipe, canal interno, contatos e WhatsApp.
 */
export default function ClientHub({ team, canManage, isAgency, month, posts, onOpenItem, onChanged }: {
  team: boolean; canManage: boolean; isAgency: boolean; month: string;
  posts: { id: string; title: string }[]; onOpenItem: (id: string) => void; onChanged: () => void;
}) {
  const clientId = getActiveClientId();
  const tabs: HubTab[] = team ? ["conversa", "equipe", "tarefas", "conhecimento", "linha", "pedidos", "referencias", "contatos", "mensagens"]
    : ["conversa", "tarefas", "conhecimento", "linha", "pedidos", "referencias"];
  const [state, setState] = useState(remembered);
  const tab: HubTab = state.tab && tabs.includes(state.tab) ? state.tab : "conversa";
  const [unread, setUnread] = useState<Partial<Record<ChatChannel, number>>>({});

  const save = (next: { open: boolean; tab: HubTab | null }) => {
    setState(next);
    try { window.localStorage.setItem(STORE, JSON.stringify(next)); } catch { /* sem armazenamento: só não lembra */ }
  };
  const refreshUnread = useCallback(() => { chatUnread().then((r) => setUnread(r.unread || {})).catch(() => undefined); }, []);
  useEffect(() => { refreshUnread(); const t = window.setInterval(refreshUnread, 60000); return () => window.clearInterval(t); }, [refreshUnread, clientId]);
  const markRead = useCallback(() => { window.setTimeout(refreshUnread, 300); }, [refreshUnread]);

  const total = (unread.cliente || 0) + (team ? unread.equipe || 0 : 0);
  return <section className={`clientHub${state.open ? " is-open" : ""}`} aria-label="Painel do cliente">
    <header className="clientHubHead">
      <button type="button" className="clientHubToggle" aria-expanded={state.open} onClick={() => save({ ...state, open: !state.open })}>
        <span>{team ? "Cliente" : "Com a Mugô"}</span>{total ? <i className="hubBadge">{total}</i> : null}<em aria-hidden="true">{state.open ? "▾" : "▸"}</em>
      </button>
      {state.open ? <div className="studioTabs clientHubTabs" role="tablist" aria-label="Painel do cliente">
        {tabs.map((t) => {
          const n = t === "conversa" ? unread.cliente : t === "equipe" ? unread.equipe : 0;
          return <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "is-active" : ""} onClick={() => save({ open: true, tab: t })}>
            {LABELS[t]}{n ? <i className="hubBadge">{n}</i> : null}
          </button>;
        })}
      </div> : null}
    </header>
    {state.open ? <div className="clientHubBody">
      {tab === "conversa" ? <BrandChat key={`c-${clientId}`} channel="cliente" posts={posts} onOpenItem={onOpenItem} onRead={markRead} /> : null}
      {tab === "equipe" && team ? <BrandChat key={`e-${clientId}`} channel="equipe" posts={posts} onOpenItem={onOpenItem} onRead={markRead} /> : null}
      {tab === "tarefas" ? (team ? <TaskBoard key={clientId} /> : <ClientTasks isAgency={false} clientId={clientId} standalone />) : null}
      {tab === "conhecimento" ? <BrandKnowledge key={clientId} canManage={canManage} /> : null}
      {tab === "linha" ? <BrandTimeline key={clientId} onOpenItem={onOpenItem} /> : null}
      {["pedidos", "referencias", "contatos", "mensagens"].includes(tab) ? <Approval key={`${tab}-${clientId}`} embedded month={month}
        tabs={[tab as "pedidos" | "referencias" | "contatos" | "mensagens"]} canManage={canManage} isAgency={isAgency} onChanged={onChanged} /> : null}
    </div> : null}
  </section>;
}
