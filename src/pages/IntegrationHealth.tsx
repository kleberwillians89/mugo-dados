import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { AppRoute } from "../app/routes";
import { getDataAudit, getIntegrationCenter, STATE_LABEL, type AuditStatus, type CenterCompany, type DataAudit, type IntegrationCenter, type SourceState } from "../app/integrationCenter";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";
import "../styles/integrationHealth.css";

type Filter = "problems" | "all";
const TONE: Record<SourceState, string> = {
  reauth_required: "bad", attention: "bad", stale: "warn", updating: "info", no_data: "warn", synced: "ok", not_connected: "off",
};

function ago(iso: string | null): string {
  if (!iso) return "nunca";
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return "—";
  const min = Math.round(ms / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `há ${h} h`;
  return `há ${Math.round(h / 24)} dias`;
}

/** Central de saúde das integrações: todas as empresas e fontes, do mais grave para o mais tranquilo. */
export default function IntegrationHealth({ onOpen }: { onOpen?: (clientId: string, route: AppRoute) => void }) {
  const [data, setData] = useState<IntegrationCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("problems");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setData(await getIntegrationCenter()); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível ler a saúde das integrações."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const companies = useMemo(() => {
    const list = data?.companies || [];
    if (filter === "all") return list;
    return list.filter((c) => c.error || c.queue.failed || c.sources.some((s) => ["reauth_required", "attention", "stale", "no_data"].includes(s.state)));
  }, [data, filter]);
  const s = data?.summary;

  return <Shell title="Saúde das integrações" variant="editorial"><div className="ds-page ihPage">
    <PageHeader company="Equipe Mugô" title="Saúde das integrações"
      dateline={<span>Todas as empresas e fontes. Última sincronização, falhas da semana, fila do WhatsApp e o que fazer.</span>}
      controls={<div className="ihControls">
        <div className="ds-segmented" role="group" aria-label="Filtro">
          <button type="button" aria-pressed={filter === "problems"} onClick={() => setFilter("problems")}>Só o que pede ação</button>
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>Todas</button>
        </div>
        <button type="button" className="ds-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={15} aria-hidden="true" /> {loading ? "Lendo…" : "Atualizar"}
        </button>
      </div>} />
    {error ? <p role="alert" className="studioError">{error}</p> : null}

    {s ? <div className="ihKpis" aria-label="Resumo">
      <div className={s.problems ? "is-bad" : ""}><b>{s.problems}</b><span>com erro ou reconexão</span></div>
      <div className={s.stale ? "is-warn" : ""}><b>{s.stale}</b><span>atrasadas</span></div>
      <div className="is-ok"><b>{s.ok}<small>/{s.connections}</small></b><span>em dia</span></div>
      <div><b>{s.updating}</b><span>sincronizando agora</span></div>
      <div className={s.failures_7d ? "is-warn" : ""}><b>{s.failures_7d}</b><span>falhas em 7 dias</span></div>
      <div className={data?.queue.failed ? "is-bad" : ""}><b>{data?.queue.waiting ?? 0}<small> · {data?.queue.failed ?? 0} falhou</small></b><span>fila do WhatsApp</span></div>
    </div> : loading ? <p className="ihMuted" role="status">Lendo todas as empresas…</p> : null}

    {data && !companies.length ? <p className="ihAllGood">Nenhuma integração pedindo ação agora. {s?.ok} de {s?.connections} conexões em dia.</p> : null}

    <div className="ihList">{companies.map((c) => <CompanyCard key={c.id} company={c} onOpen={onOpen} />)}</div>
    {data ? <p className="ihFoot">Lido {ago(data.generated_at)} · janela de {data.window.start.split("-").reverse().join("/")} a {data.window.end.split("-").reverse().join("/")}.
      O estado de cada fonte usa a mesma régua do painel de cada empresa (intervalo esperado de cada provedor).</p> : null}
  </div></Shell>;
}

const AUDIT_LABEL: Record<AuditStatus, string> = { ok: "Confere", warn: "Vale olhar", bad: "Problema", na: "Sem dado" };
const AUDIT_TONE: Record<AuditStatus, string> = { ok: "ok", warn: "warn", bad: "bad", na: "off" };
const nf1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

/** Auditoria cruzada da empresa: cada conferência com o número, a causa provável e o que fazer. */
function AuditPanel({ clientId }: { clientId: string }) {
  const [audit, setAudit] = useState<DataAudit | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getDataAudit(clientId).then((a) => { if (alive) setAudit(a); })
      .catch((cause) => { if (alive) setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível auditar agora."); });
    return () => { alive = false; };
  }, [clientId]);
  if (error) return <p className="studioError" role="alert">{error}</p>;
  if (!audit) return <p className="ihMuted" role="status">Conferindo loja, GA4, Meta e Google…</p>;
  const order: AuditStatus[] = ["bad", "warn", "ok", "na"];
  const checks = [...audit.checks].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status));
  return <div className="ihAudit" aria-label="Auditoria cruzada">
    <p className="ihAuditHead">
      <b>Auditoria de {audit.period.start.split("-").reverse().join("/")} a {audit.period.end.split("-").reverse().join("/")}</b>
      <span>Loja ({audit.store.provider || "não conectada"}) como fonte da verdade.</span>
      {(["bad", "warn", "ok"] as AuditStatus[]).map((st) => audit.summary[st] ? <span key={st} className={`ihPill is-${AUDIT_TONE[st]}`}>{audit.summary[st]} {AUDIT_LABEL[st].toLowerCase()}</span> : null)}
    </p>
    <ul>{checks.map((c) => <li key={c.key} className={`is-${c.status}`}>
      <div className="ihAuditTop">
        <span className={`ihPill is-${AUDIT_TONE[c.status]}`}>{AUDIT_LABEL[c.status]}</span>
        <b>{c.title}</b>
        {c.value != null ? <span className="ihAuditValue">{nf1.format(c.value)}{c.unit === "%" ? "%" : ` ${c.unit}`}</span> : null}
      </div>
      <p>{c.detail}</p>
      {c.cause ? <p className="ihAuditCause"><b>Causa provável:</b> {c.cause}</p> : null}
      {c.todo ? <p className="ihAuditTodo"><b>O que fazer:</b> {c.todo}</p> : null}
    </li>)}</ul>
  </div>;
}

function CompanyCard({ company, onOpen }: { company: CenterCompany; onOpen?: (clientId: string, route: AppRoute) => void }) {
  const [auditing, setAuditing] = useState(false);
  const connected = company.sources.filter((s) => s.state !== "not_connected");
  const off = company.sources.filter((s) => s.state === "not_connected");
  return <section className="ihCard" aria-labelledby={`ih-${company.id}`}>
    <header>
      <h2 id={`ih-${company.id}`}>{company.name}</h2>
      {company.queue.waiting || company.queue.failed ? <span className={`ihPill is-${company.queue.failed ? "bad" : "info"}`}>
        WhatsApp: {company.queue.waiting} na fila{company.queue.failed ? ` · ${company.queue.failed} falhou` : ""}</span> : null}
      <button type="button" className="ds-button" aria-expanded={auditing} onClick={() => setAuditing((v) => !v)}>{auditing ? "Fechar auditoria" : "Auditar dados"}</button>
      {onOpen ? <button type="button" className="ds-button" onClick={() => onOpen(company.id, "integrations")}>Abrir integrações</button> : null}
    </header>
    {auditing ? <AuditPanel clientId={company.id} /> : null}
    {company.error ? <p className="studioError" role="alert">{company.error}</p> : null}
    {connected.length ? <table className="ds-table ihTable">
      <thead><tr><th>Fonte</th><th>Estado</th><th>Último sucesso</th><th>Último dado</th><th className="is-number">Falhas 7d</th><th>O que fazer</th></tr></thead>
      <tbody>{connected.map((src) => <tr key={src.provider}>
        <td className="is-primary">{src.label}</td>
        <td><span className={`ihPill is-${TONE[src.state]}`}>{STATE_LABEL[src.state]}</span></td>
        <td title={src.last_success_at || ""}>{ago(src.last_success_at)}</td>
        <td>{src.last_data_at ? src.last_data_at.slice(0, 10).split("-").reverse().join("/") : "—"}</td>
        <td className="is-number">{src.failures_7d || "—"}</td>
        <td className="ihHint">{src.hint}{src.error_code && src.state !== "synced" ? <code>{src.error_code}</code> : null}</td>
      </tr>)}</tbody>
    </table> : <p className="ihMuted">Nenhuma fonte conectada.</p>}
    {off.length ? <p className="ihMuted">Não conectadas: {off.map((s) => s.label).join(", ")}.</p> : null}
  </section>;
}
