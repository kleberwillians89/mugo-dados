import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  AUDIENCE, DELIVERY, OUTBOX_STATUS, OWNER, calendarStart, deleteTeamMember, getOutbox, getOverview, getResponses, getUsage,
  listAllMeetings, listGoogleCalendars, listTeam, processQueue, saveTeamMember, selectGoogleCalendar, simulateAutomation,
  syncCatalog, syncGoogleCalendar, updateAutomation, when,
  type Automation, type Meeting, type OutboxItem, type Overview, type ResponseItem, type Simulation, type TeamInput, type TeamMember, type Usage,
} from "../app/automations";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import SegmentedControl from "../components/data/SegmentedControl";
import Drawer from "../components/Drawer";
import "../styles/automations.css";

type Tab = "automacoes" | "historico" | "respostas" | "consumo" | "equipe" | "reunioes";
const TABS = [
  { id: "automacoes", label: "Automações" }, { id: "historico", label: "Histórico" }, { id: "respostas", label: "Respostas" },
  { id: "consumo", label: "Consumo" }, { id: "equipe", label: "Equipe" }, { id: "reunioes", label: "Reuniões" },
];
const EMPTY_MEMBER: TeamInput = { name: "", email: "", phone: "", active: true, receives_internal: true, receives_campaign_alerts: false };
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

function Flag({ ok, label, hint }: { ok: boolean; label: string; hint?: string }) {
  return <span className={`autoFlag ${ok ? "is-ok" : "is-off"}`} title={hint}><i aria-hidden="true" />{label}</span>;
}

function StateBadges({ a }: { a: Automation }) {
  if (a.owner !== "dados") return <span className="autoOwner">{a.owner === "crm" ? "Disparada pelo CRM" : "Sem disparo automático"}</span>;
  return <div className="autoStates">
    <Flag ok={a.state.automation_enabled} label="Habilitada" />
    <Flag ok={a.state.template_approved} label="Aprovado na Meta" />
    <Flag ok={a.state.integration_configured} label="Integração" />
    <Flag ok={a.state.operational} label={a.state.simulated_only && a.state.template_approved ? "Só simulação" : "Operacional"} />
  </div>;
}

export default function Automations() {
  const [tab, setTab] = useState<Tab>("automacoes");
  const [data, setData] = useState<Overview | null>(null);
  const [outbox, setOutbox] = useState<OutboxItem[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [responses, setResponses] = useState<ResponseItem[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [calendars, setCalendars] = useState<{ id: string; summary: string; primary: boolean }[] | null>(null);
  const [editingMember, setEditingMember] = useState<(TeamInput & { id?: string }) | null>(null);
  const [simulating, setSimulating] = useState<{ a: Automation; params: Record<string, string>; result: Simulation | null } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setData(await getOverview()); } catch (cause) { setError(message(cause, "Não foi possível carregar a central.")); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("calendar") === "connected") setNotice("Google Calendar autorizado. Escolha a agenda da Mugô.");
    if (params.get("calendar") === "error") setError(params.get("error") || "Autorização do Google Calendar não concluída.");
  }, []);
  useEffect(() => {
    const run = async () => {
      try {
        if (tab === "historico") setOutbox((await getOutbox(statusFilter || undefined)).items);
        if (tab === "respostas") setResponses((await getResponses()).items);
        if (tab === "consumo") setUsage(await getUsage());
        if (tab === "equipe") setTeam((await listTeam()).items);
        if (tab === "reunioes") {
          const start = new Date(); const end = new Date(Date.now() + 30 * 86400000);
          setMeetings((await listAllMeetings(start.toISOString(), end.toISOString())).items);
        }
      } catch (cause) { setError(message(cause, "Não foi possível carregar esta aba.")); }
    };
    void run();
  }, [tab, statusFilter]);

  async function run<T>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }

  async function toggle(a: Automation) {
    const updated = await run(`t:${a.key}`, () => updateAutomation(a.key, { automation_enabled: !a.automation_enabled }), "Não foi possível alterar.");
    if (updated) await load();
  }

  async function saveLead(a: Automation, hours: number) {
    if (!Number.isFinite(hours) || hours < 0) return;
    const updated = await run(`l:${a.key}`, () => updateAutomation(a.key, { lead_minutes: Math.round(hours * 60) }), "Não foi possível salvar a antecedência.");
    if (updated) await load();
  }

  async function connectCalendar() {
    const out = await run("cal", calendarStart, "Não foi possível iniciar a autorização.");
    if (out?.url) window.location.assign(out.url);
  }

  async function submitMember(event: FormEvent) {
    event.preventDefault();
    if (!editingMember) return;
    const { id, ...input } = editingMember;
    const saved = await run("member", () => saveTeamMember({ ...input, phone: input.phone || null }, id), "Não foi possível salvar.");
    if (saved) { setEditingMember(null); setTeam((await listTeam()).items); }
  }

  const flags = data?.flags;
  const calendar = flags?.calendar;
  const groups: [string, Automation[]][] = data ? [
    ["Disparadas pelo Mugô Dados", data.automations.filter((a) => a.owner === "dados")],
    ["Disparadas pelo CRM Mugô (tarefas, financeiro, leads)", data.automations.filter((a) => a.owner === "crm")],
    ["Técnico", data.automations.filter((a) => a.owner === "tecnico")],
  ] : [];

  return <Shell title="Automações" variant="editorial"><div className="ds-page autoPage">
    <div className="autoIntro">
      <PageHeader company="Mugô" title="Automações do WhatsApp" />
      <p>Mensagens pelo número oficial da Mugô (WhatsApp Cloud API). O status de cada template vem da Meta; nada é marcado como aprovado aqui.</p>
    </div>

    {flags ? <section className="autoCard autoStatus" aria-label="Situação das integrações">
      <div>
        <h2>Envio</h2>
        <Flag ok={flags.send_enabled} label={flags.send_enabled ? "Envio real ligado" : "Modo simulado (nenhuma mensagem sai)"} />
        <Flag ok={flags.mugozap_configured} label="MugôZap (número oficial)" />
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={async () => {
          const out = await run("process", processQueue, "Não foi possível processar a fila.");
          if (out) setNotice(`Fila processada: ${Object.entries(out).filter(([k]) => k !== "send_enabled").map(([k, v]) => `${k} ${v}`).join(" · ")}`);
        }}>{busy === "process" ? "Processando…" : "Processar fila agora"}</button>
      </div>
      <div>
        <h2>Templates da Meta</h2>
        <Flag ok={flags.catalog_configured} label={flags.catalog_configured ? "Leitura configurada" : "WABA/token não configurados"} />
        <small>{flags.catalog_synced_at ? `Sincronizado em ${when(flags.catalog_synced_at)}` : "Ainda não sincronizado"}</small>
        <button type="button" className="ds-button" disabled={Boolean(busy) || !flags.catalog_configured} onClick={async () => {
          const out = await run("sync", syncCatalog, "Não foi possível sincronizar com a Meta.");
          if (out) { setNotice(`${out.templates} template(s) lidos da Meta, ${out.approved} aprovado(s).`); await load(); }
        }}>{busy === "sync" ? "Sincronizando…" : "Sincronizar com a Meta"}</button>
      </div>
      <div>
        <h2>Google Calendar</h2>
        <Flag ok={calendar?.status === "ativo"} label={calendar?.status === "ativo" ? `Ativo: ${calendar.calendar_summary}` : calendar?.status === "aguardando_calendario" ? "Escolha a agenda" : calendar?.status === "reautorizar" ? "Reautorizar" : "Desconectado"} />
        {calendar?.account_email ? <small>{calendar.account_email}{calendar.last_sync_at ? ` · sincronizado ${when(calendar.last_sync_at)}` : ""}{calendar.webhook ? " · avisos em tempo real" : ""}</small> : null}
        {calendar?.last_error ? <small className="autoError">{calendar.last_error}</small> : null}
        <div className="autoRow">
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void connectCalendar()}>{calendar?.account_email ? "Reconectar" : "Conectar conta Mugô"}</button>
          {calendar?.account_email ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={async () => {
            const out = await run("cals", listGoogleCalendars, "Não foi possível listar as agendas."); if (out) setCalendars(out.items);
          }}>Escolher agenda</button> : null}
          {calendar?.status === "ativo" ? <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={async () => {
            const out = await run("calsync", syncGoogleCalendar, "Não foi possível sincronizar."); if (out) { setNotice(`${out.changed} evento(s) atualizados.`); await load(); }
          }}>{busy === "calsync" ? "Sincronizando…" : "Sincronizar agora"}</button> : null}
        </div>
        {calendars ? <select aria-label="Agenda da Mugô" defaultValue="" onChange={async (e) => {
          const id = e.target.value; if (!id) return;
          const out = await run("select", () => selectGoogleCalendar(id), "Não foi possível usar esta agenda.");
          if (out) { setCalendars(null); setNotice(`Agenda conectada: ${out.changed} evento(s) importados.`); await load(); }
        }}>
          <option value="">Selecione a agenda…</option>
          {calendars.map((c) => <option key={c.id} value={c.id}>{c.summary}{c.primary ? " (principal)" : ""}</option>)}
        </select> : null}
      </div>
    </section> : null}

    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    {notice ? <div className="ds-notice"><p>{notice}</p></div> : null}

    <SegmentedControl ariaLabel="Seções" options={TABS} value={tab} onSelect={(id) => setTab(id as Tab)} />

    {tab === "automacoes" ? <div className="autoGroups">
      {!data ? <p>Carregando…</p> : groups.map(([title, list]) => list.length ? <section key={title} className="autoCard">
        <h2>{title}</h2>
        <div className="autoScroll"><table className="ds-table autoTable">
          <thead><tr><th>Automação</th><th>Template na Meta</th><th>Situação</th><th>Destinatários</th><th>Antecedência</th><th aria-label="Ações" /></tr></thead>
          <tbody>{list.map((a) => <tr key={a.key}>
            <td><strong>{a.trigger_label}</strong><small>{a.template_name}{a.crm_reference ? ` · ${a.crm_reference}` : ""}</small>
              {a.notes ? <small>{a.notes}</small> : null}</td>
            <td>{a.template ? <><span className={`autoMeta is-${a.template.status.toLowerCase()}`}>{a.template.status}</span>
              <small>{a.template.category} · {a.template.language} · {a.template.body_param_count} variável(is)</small>
              {a.template.rejected_reason ? <small className="autoError">{a.template.rejected_reason}</small> : null}</> : <small>Não encontrado na Meta</small>}</td>
            <td><StateBadges a={a} />{a.state.problems.filter((p) => !p.includes("CRM") || a.owner !== "crm").map((p) => <small key={p} className="autoProblem">{p}</small>)}</td>
            <td>{AUDIENCE[a.audience]}{a.schedule?.time ? <small>{a.schedule.time} · {(a.schedule.weekdays || []).length === 5 ? "seg a sex" : (a.schedule.weekdays || []).includes(5) ? "sexta" : "dias definidos"}</small> : null}</td>
            <td>{a.owner === "dados" && a.lead_minutes != null ? <label className="autoLead"><input type="number" min={0} step={1} defaultValue={a.lead_minutes / 60}
              aria-label={`Antecedência em horas: ${a.trigger_label}`} onBlur={(e) => { const h = Number(e.target.value); if (h * 60 !== a.lead_minutes) void saveLead(a, h); }} /> h</label> : "—"}</td>
            <td><div className="autoActions">
              {a.owner === "dados" ? <>
                <button type="button" className={`ds-button${a.automation_enabled ? "" : " is-primary"}`} disabled={Boolean(busy)} onClick={() => void toggle(a)}>
                  {a.automation_enabled ? "Desativar" : "Ativar"}</button>
                <button type="button" className="ds-button" onClick={() => setSimulating({ a, params: Object.fromEntries(a.variable_map.map((k) => [k, ""])), result: null })}>Simular</button>
              </> : <small>{OWNER[a.owner]}</small>}
            </div></td>
          </tr>)}</tbody>
        </table></div>
      </section> : null)}
      {data?.other_templates.length ? <section className="autoCard"><h2>Outros templates na Meta</h2>
        <p className="autoMuted">{data.other_templates.map((t) => `${t.name} (${t.status})`).join(" · ")}</p></section> : null}
    </div> : null}

    {tab === "historico" ? <section className="autoCard">
      <div className="autoRow"><h2>Histórico de envios</h2>
        <select value={statusFilter} aria-label="Filtrar status" onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">Todos</option>{Object.entries(OUTBOX_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select></div>
      {!outbox.length ? <p className="autoMuted">Nada na fila ainda.</p> : <div className="autoScroll"><table className="ds-table autoTable">
        <thead><tr><th>Quando</th><th>Automação</th><th>Destinatário</th><th>Status</th><th>Tentativas / erro</th></tr></thead>
        <tbody>{outbox.map((o) => <tr key={o.id}>
          <td>{when(o.scheduled_for)}<small>criado {when(o.created_at)}</small></td>
          <td>{o.automation_key}<small>{o.client_id || "equipe"} · {o.source_type}</small></td>
          <td>{o.recipient_name || "—"}<small>{o.recipient_phone}</small></td>
          <td><span className={`autoStatusTag is-${o.status}`}>{OUTBOX_STATUS[o.status] || o.status}</span>{o.delivery_status ? <small>{DELIVERY[o.delivery_status]}</small> : null}</td>
          <td>{o.attempts}{o.last_error ? <small className="autoError">{o.last_error}</small> : null}{o.cancelled_reason ? <small>{o.cancelled_reason}</small> : null}
            {o.next_attempt_at && o.status === "agendado" ? <small>nova tentativa {when(o.next_attempt_at)}</small> : null}</td>
        </tr>)}</tbody></table></div>}
    </section> : null}

    {tab === "respostas" ? <section className="autoCard"><h2>Respostas recebidas</h2>
      {!responses.length ? <p className="autoMuted">Nenhuma resposta registrada.</p> : <div className="autoScroll"><table className="ds-table autoTable">
        <thead><tr><th>Quando</th><th>Empresa</th><th>Telefone</th><th>Resposta</th><th>Resultado</th></tr></thead>
        <tbody>{responses.map((r) => <tr key={r.id}><td>{when(r.received_at)}</td><td>{r.client_id || "—"}</td><td>{r.phone_masked || "—"}</td>
          <td>{r.answer_raw || "—"}<small>{r.answer_key}</small></td><td>{r.result || "—"}</td></tr>)}</tbody></table></div>}
    </section> : null}

    {tab === "consumo" ? <section className="autoCard"><h2>Consumo do mês</h2>
      {!usage ? <p>Carregando…</p> : <>
        <ul className="autoChips">{Object.entries(usage.by_status).map(([k, v]) => <li key={k}>{OUTBOX_STATUS[k] || k}: {v}</li>)}</ul>
        <p>Enviadas por categoria: {Object.entries(usage.sent_by_category).map(([k, v]) => `${k} ${v}`).join(" · ") || "nenhuma"}</p>
        <p>Custo estimado: {usage.estimated_cost_brl == null ? "configure as tarifas para estimar" : usage.estimated_cost_brl.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</p>
        <small className="autoMuted">{usage.cost_note}</small>
      </>}
    </section> : null}

    {tab === "equipe" ? <section className="autoCard">
      <div className="autoRow"><h2>Equipe Mugô</h2><button type="button" className="ds-button is-primary" onClick={() => setEditingMember({ ...EMPTY_MEMBER })}>+ Pessoa</button></div>
      <p className="autoMuted">Recebe lembretes de reuniões internas e, se marcado, alertas de campanha. O e-mail liga a pessoa aos convites do Google Calendar; o telefone precisa estar cadastrado também no CRM.</p>
      {!team.length ? <p className="autoMuted">Ninguém cadastrado.</p> : <ul className="autoTeam">{team.map((m) => <li key={m.id}>
        <div><strong>{m.name}</strong><small>{m.email} · {m.phone || "sem telefone"}</small></div>
        <small>{[m.receives_internal && "reuniões internas", m.receives_campaign_alerts && "alertas de campanha", !m.active && "inativo"].filter(Boolean).join(" · ")}</small>
        <button type="button" className="ds-button" onClick={() => setEditingMember({ ...m, phone: m.phone || "" })}>Editar</button>
        <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={async () => { const ok = await run("del", () => deleteTeamMember(m.id), "Não foi possível remover."); if (ok !== null) setTeam((await listTeam()).items); }}>Remover</button>
      </li>)}</ul>}
    </section> : null}

    {tab === "reunioes" ? <section className="autoCard"><h2>Próximos 30 dias</h2>
      {!meetings.length ? <p className="autoMuted">Nenhuma reunião sincronizada.</p> : <ul className="autoTeam">{meetings.map((m) => <li key={m.google_event_id}>
        <div><strong>{m.summary || "Reunião"}</strong><small>{m.all_day ? "dia todo" : when(m.start_at)}</small></div>
        <small>{m.kind === "interna" ? "Interna" : m.kind === "cliente" ? `Cliente: ${m.client_id}` : "Sem lembrete automático"}</small>
        {m.html_link ? <a href={m.html_link} target="_blank" rel="noreferrer">Abrir no Google</a> : null}
      </li>)}</ul>}
    </section> : null}

    <Drawer open={Boolean(editingMember)} title={editingMember?.id ? "Editar pessoa" : "Nova pessoa da equipe"} onClose={() => { if (!busy) setEditingMember(null); }}>
      {editingMember ? <form className="autoForm" onSubmit={submitMember}>
        <label>Nome<input required value={editingMember.name} onChange={(e) => setEditingMember({ ...editingMember, name: e.target.value })} /></label>
        <label>E-mail (o mesmo do Google)<input required type="email" value={editingMember.email} onChange={(e) => setEditingMember({ ...editingMember, email: e.target.value })} /></label>
        <label>WhatsApp (DDI + DDD + número)<input value={editingMember.phone || ""} inputMode="tel" onChange={(e) => setEditingMember({ ...editingMember, phone: e.target.value })} placeholder="5511999999999" /></label>
        <label className="autoCheck"><input type="checkbox" checked={editingMember.receives_internal} onChange={(e) => setEditingMember({ ...editingMember, receives_internal: e.target.checked })} /> Lembretes de reuniões internas</label>
        <label className="autoCheck"><input type="checkbox" checked={editingMember.receives_campaign_alerts} onChange={(e) => setEditingMember({ ...editingMember, receives_campaign_alerts: e.target.checked })} /> Alertas de campanha</label>
        <label className="autoCheck"><input type="checkbox" checked={editingMember.active} onChange={(e) => setEditingMember({ ...editingMember, active: e.target.checked })} /> Ativo</label>
        <div className="autoRow"><button type="button" className="ds-button" onClick={() => setEditingMember(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "member" ? "Salvando…" : "Salvar"}</button></div>
      </form> : null}
    </Drawer>

    <Drawer open={Boolean(simulating)} title={simulating ? `Simular: ${simulating.a.trigger_label}` : ""} description="Teste sem envio: mostra o texto final e se a automação bloquearia." onClose={() => setSimulating(null)}>
      {simulating ? <form className="autoForm" onSubmit={async (e) => {
        e.preventDefault();
        const result = await run("sim", () => simulateAutomation(simulating.a.key, simulating.params), "Não foi possível simular.");
        if (result) setSimulating({ ...simulating, result });
      }}>
        {simulating.a.variable_map.map((k, i) => <label key={k}>{`{{${i + 1}}} ${k}`}<input value={simulating.params[k] || ""} onChange={(e) => setSimulating({ ...simulating, params: { ...simulating.params, [k]: e.target.value } })} /></label>)}
        <button className="ds-button is-primary" disabled={Boolean(busy)}>Simular</button>
        {simulating.result ? <div className={`ds-notice ${simulating.result.would_send ? "" : "is-warning"}`}>
          <p className="ds-noticeTitle">{simulating.result.would_send ? "Passaria em todas as validações (nada foi enviado)." : `Bloqueada: ${simulating.result.blocked_reason}`}</p>
          {simulating.result.text ? <p className="autoPreview">{simulating.result.text}</p> : null}
        </div> : null}
      </form> : null}
    </Drawer>
  </div></Shell>;
}
