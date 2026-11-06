import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckSquare, Flag, MessageCircle, Sparkles } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../../app/activeClient";
import { dueInfo, listClientTasks, listCrmTasks } from "../../app/crm";
import { chatUnread, getKnowledge, listChat, listTimeline, type ChatChannel, type ChatMessage, type TimelineEvent } from "../../app/studio";
import Approval from "../../pages/Approval";
import Drawer from "../Drawer";
import { ago } from "../../app/ago";
import BrandChat from "./BrandChat";
import BrandKnowledge from "./BrandKnowledge";
import ClientTasks from "./ClientTasks";
import TaskBoard from "./TaskBoard";

type Panel = "ajustes" | "conversa" | "tarefas" | "ia" | "mais";
type Post = { id: string; title: string; status?: string };
type Summary = { lastAdjust: TimelineEvent | null; events: TimelineEvent[]; unread: Partial<Record<ChatChannel, number>>;
  lastMessage: ChatMessage | null; lateTasks: number | null; openTasks: number | null; sources: number | null };
const EMPTY: Summary = { lastAdjust: null, events: [], unread: {}, lastMessage: null, lateTasks: null, openTasks: null, sources: null };
const CLIENT_KINDS = ["ajuste_solicitado", "editado_pelo_cliente", "comentario", "aprovado"];
const TAGS: Record<string, [string, string]> = { ajuste_solicitado: ["Ajuste pedido", "r"], editado_pelo_cliente: ["Editado pelo cliente", "y"],
  comentario: ["Comentário", "b"], aprovado: ["Aprovado", "g"] };

export { ago };
const clip = (text: string | null | undefined, n: number) => { const t = String(text || "").replace(/\s+/g, " ").trim(); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };

/**
 * Proposta A: quatro cartões de resumo acima do calendário (o que pede atenção em um olhar)
 * e uma gaveta lateral com o detalhe só quando a pessoa clica. O calendário continua com a tela toda.
 */
export default function ClientHub({ team, canManage, isAgency, month, posts, onOpenItem, onChanged }: {
  team: boolean; canManage: boolean; isAgency: boolean; month: string;
  posts: Post[]; onOpenItem: (id: string) => void; onChanged: () => void;
}) {
  const clientId = getActiveClientId();
  const brand = getActiveClientName() || "Cliente";
  const [summary, setSummary] = useState<Summary>(EMPTY);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [cite, setCite] = useState<string>("");

  const load = useCallback(async () => {
    const settle = <T,>(p: Promise<T>) => p.then((v) => v, () => null);
    const [timeline, unread, chat, tasks, knowledge] = await Promise.all([
      settle(listTimeline()), settle(chatUnread()), settle(listChat("cliente")),
      settle<{ available: boolean; tasks?: { status: string; due_date: string | null }[] }>(team ? listCrmTasks() : listClientTasks()), settle(getKnowledge()),
    ]);
    if (getActiveClientId() !== clientId) return;
    const events = (timeline?.events || []).filter((e) => CLIENT_KINDS.includes(e.kind));
    const messages = chat?.messages || [];
    const list = tasks && tasks.available ? tasks.tasks || [] : null;
    const open = list?.filter((t) => t.status === "pending" || t.status === "in_progress") || null;
    setSummary({ events, lastAdjust: events.find((e) => e.kind === "ajuste_solicitado") || null, unread: unread?.unread || {},
      lastMessage: [...messages].reverse().find((m) => !m.mine) || null,
      lateTasks: open ? open.filter((t) => dueInfo(t.due_date).late).length : null, openTasks: open ? open.length : null,
      sources: knowledge ? knowledge.sources : null });
  }, [clientId, team]);
  useEffect(() => { setSummary(EMPTY); void load(); const t = window.setInterval(() => void load(), 60000); return () => window.clearInterval(t); }, [load]);
  // Estável: a conversa avisa "li" a cada leitura; uma função nova a cada render faria ela recarregar em laço.
  const refresh = useCallback(() => { void load(); }, [load]);

  const adjusts = posts.filter((p) => p.status === "rejeitado").length;
  const unreadTotal = (summary.unread.cliente || 0) + (team ? summary.unread.equipe || 0 : 0);
  const open = (p: Panel) => setPanel(p);
  const reply = (itemId: string | null) => { setCite(itemId || ""); setPanel("conversa"); };

  const cards = [
    { id: "ajustes" as const, icon: Flag, label: "Ajustes pedidos", value: String(adjusts), alert: adjusts > 0, cta: "Ver",
      sub: summary.lastAdjust ? `Último: ${clip(summary.lastAdjust.actor, 16)} ${ago(summary.lastAdjust.at)} · “${clip(summary.lastAdjust.title, 26)}”` : adjusts ? "Posts esperando a correção" : "Nada pendente neste mês" },
    { id: "conversa" as const, icon: MessageCircle, label: "Conversa", value: unreadTotal ? `${unreadTotal} nova${unreadTotal > 1 ? "s" : ""}` : "Em dia", alert: unreadTotal > 0, cta: "Abrir",
      sub: summary.lastMessage ? `${clip(summary.lastMessage.author_name || "Cliente", 14)}: “${clip(summary.lastMessage.body, 40)}”` : team ? "Fale com o cliente ou só com a equipe" : "Fale com a equipe Mugô" },
    { id: "tarefas" as const, icon: CheckSquare, label: "Tarefas", alert: Boolean(summary.lateTasks), cta: "Ver",
      value: summary.lateTasks ? `${summary.lateTasks} atrasada${summary.lateTasks > 1 ? "s" : ""}` : summary.openTasks !== null ? `${summary.openTasks} em aberto` : "—",
      sub: summary.openTasks !== null ? `${summary.openTasks} em aberto no total` : "Ligação com o CRM indisponível" },
    { id: "ia" as const, icon: Sparkles, label: "IA da marca", alert: false, cta: canManage ? "Ensinar" : "Ver",
      value: summary.sources === null ? "—" : `${summary.sources} fonte${summary.sources === 1 ? "" : "s"}`,
      sub: summary.sources ? "Quanto mais material, melhores as pautas" : "Envie a apresentação ou o cardápio da marca" },
  ];
  const tabs: { id: Panel; label: string; n?: number }[] = [
    { id: "ajustes", label: "Ajustes", n: adjusts }, { id: "conversa", label: "Conversa", n: unreadTotal },
    { id: "tarefas", label: "Tarefas" }, { id: "ia", label: "IA da marca" }, { id: "mais", label: team ? "Mais" : "Referências" },
  ];
  const TITLES: Record<Panel, [string, string]> = {
    ajustes: ["Ajustes pedidos", "O que o cliente pediu, aprovou ou mudou — do mais recente ao mais antigo."],
    conversa: ["Conversa", team ? "Com o cliente, ou só entre a equipe. Mensagem do cliente avisa o time no WhatsApp." : "Fale com a equipe Mugô."],
    tarefas: ["Tarefas", team ? "Do CRM Mugô, onde a tarefa muda de etapa." : "O que está em andamento com a Mugô."],
    ia: ["IA da marca", "Documentos ensinam a IA e são descartados. Ela usa isso nas pautas e nas respostas."],
    mais: team ? ["Mais", "Pedidos enviados, referências, contatos e WhatsApp."] : ["Referências", "Links e artes que vocês gostam."],
  };

  return <>
    <div className="desk" role="group" aria-label={`Resumo do cliente ${brand}`}>
      {cards.map((c) => { const Icon = c.icon; return <button key={c.id} type="button" className={`deskCard${c.alert ? " is-alert" : ""}`} onClick={() => open(c.id)}>
        <span className="deskTop"><span className="deskLabel"><Icon size={15} aria-hidden="true" />{c.label}</span><span className="deskCta">{c.cta} <ArrowRight size={13} aria-hidden="true" /></span></span>
        <span className="deskValue">{c.value}</span>
        <span className="deskSub">{c.sub}</span>
      </button>; })}
    </div>
    <Drawer open={panel !== null} width="lg" title={panel ? `${TITLES[panel][0]} · ${brand}` : ""} description={panel ? TITLES[panel][1] : undefined} onClose={() => setPanel(null)}>
      {panel ? <div className="deskDrawer">
        <div className="deskTabs" role="tablist" aria-label="Seções">
          {tabs.map((t) => <button key={t.id} type="button" role="tab" aria-selected={panel === t.id} className={panel === t.id ? "is-active" : ""} onClick={() => setPanel(t.id)}>
            {t.label}{t.n ? <i className="hubBadge">{t.n}</i> : null}</button>)}
        </div>
        {panel === "ajustes" ? <Adjustments events={summary.events} onOpenItem={(id) => { setPanel(null); onOpenItem(id); }} onReply={reply} /> : null}
        {panel === "conversa" ? <Conversation team={team} posts={posts} cite={cite} onOpenItem={(id) => { setPanel(null); onOpenItem(id); }} onRead={refresh} /> : null}
        {panel === "tarefas" ? (team ? <TaskBoard key={clientId} /> : <ClientTasks isAgency={false} clientId={clientId} standalone />) : null}
        {panel === "ia" ? <BrandKnowledge key={clientId} canManage={canManage} /> : null}
        {panel === "mais" ? <More team={team} month={month} canManage={canManage} isAgency={isAgency} onChanged={onChanged} /> : null}
      </div> : null}
    </Drawer>
  </>;
}

function Adjustments({ events, onOpenItem, onReply }: { events: TimelineEvent[]; onOpenItem: (id: string) => void; onReply: (itemId: string | null) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  if (!events.length) return <div className="deskEmpty"><Flag size={22} aria-hidden="true" /><b>Nenhum pedido do cliente por enquanto</b><p>Quando o cliente aprovar, pedir ajuste ou comentar um post, aparece aqui.</p></div>;
  return <ul className="deskList">{events.map((e) => {
    const [label, tone] = TAGS[e.kind] || ["Atualização", "b"];
    const long = (e.detail || "").length > 180;
    return <li key={e.id} className="deskItem">
      <span className={`deskTag is-${tone}`}>{label}</span>
      <b className="deskItemTitle">{e.title || "Post"}</b>
      <small>{e.actor || "Cliente"} · {ago(e.at)}{e.changes?.length ? ` · mudou ${e.changes.join(", ")}` : ""}</small>
      {e.detail ? <p className={expanded === e.id ? "" : "is-clamped"}>“{e.detail}”</p> : null}
      {long ? <button type="button" className="kbLink" onClick={() => setExpanded(expanded === e.id ? null : e.id)}>{expanded === e.id ? "Ver menos" : "Ver tudo"}</button> : null}
      <div className="deskActions">
        {e.item_id ? <button type="button" className="ds-button is-primary" onClick={() => onOpenItem(e.item_id!)}>Abrir post</button> : null}
        {e.kind !== "aprovado" ? <button type="button" className="ds-button" onClick={() => onReply(e.item_id)}>Responder</button> : null}
      </div>
    </li>;
  })}</ul>;
}

function Conversation({ team, posts, cite, onOpenItem, onRead }: { team: boolean; posts: Post[]; cite: string; onOpenItem: (id: string) => void; onRead: () => void }) {
  const [channel, setChannel] = useState<ChatChannel>("cliente");
  return <>
    {team ? <div className="hubViews" role="tablist" aria-label="Canal">
      <button type="button" role="tab" aria-selected={channel === "cliente"} className={channel === "cliente" ? "is-active" : ""} onClick={() => setChannel("cliente")}>Com o cliente</button>
      <button type="button" role="tab" aria-selected={channel === "equipe"} className={channel === "equipe" ? "is-active" : ""} onClick={() => setChannel("equipe")}>Só equipe</button>
    </div> : null}
    <BrandChat key={`${channel}-${cite}`} channel={channel} posts={posts.map(({ id, title }) => ({ id, title }))} onOpenItem={onOpenItem} onRead={onRead}
      initialItemId={cite} placeholder={cite ? "Responda sobre este post…" : undefined} />
  </>;
}

function More({ team, month, canManage, isAgency, onChanged }: { team: boolean; month: string; canManage: boolean; isAgency: boolean; onChanged: () => void }) {
  const views = team ? (["pedidos", "referencias", "contatos", "mensagens"] as const) : (["referencias", "pedidos"] as const);
  const labels = { pedidos: "Enviados para aprovação", referencias: "Referências", contatos: "Contatos", mensagens: "WhatsApp" };
  const [view, setView] = useState<(typeof views)[number]>(views[0]);
  return <>
    <div className="hubViews" role="tablist" aria-label="Mais">
      {views.map((v) => <button key={v} type="button" role="tab" aria-selected={view === v} className={view === v ? "is-active" : ""} onClick={() => setView(v)}>{labels[v]}</button>)}
    </div>
    <Approval key={view} embedded month={month} tabs={[view]} canManage={canManage} isAgency={isAgency} onChanged={onChanged} />
  </>;
}
