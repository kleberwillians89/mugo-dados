import { useCallback, useEffect, useState } from "react";
import { getCommercialCatalog, getCommercialConfig, saveCommercialConfig, type CommercialConfig, type CommercialModuleOption, brl, getAdminPlans, removeSubscription, savePlan, saveSubscription, STATUS_LABEL, type AdminPlans, type LimitKey, type SaasPlan, type SubStatus } from "../app/saas";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";
import "../styles/saas.css";

const LIMITS: { key: LimitKey; label: string }[] = [
  { key: "users", label: "Usuários" }, { key: "email_sends_month", label: "E-mails/mês" }, { key: "whatsapp_month", label: "WhatsApp/mês" },
  { key: "ai_actions_month", label: "Ações IA/mês" }, { key: "competitors", label: "Concorrentes" }, { key: "monitored_products", label: "Produtos" },
];

function PlanEditor({ plan, onSaved }: { plan: SaasPlan; onSaved: () => void }) {
  const [draft, setDraft] = useState(plan);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  return (
    <div className="saPlan">
      <input className="saPlanName" aria-label="Nome do plano" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
      <label className="saField">R$/mês<input type="number" min={0} value={draft.price_month_cents / 100}
        onChange={(e) => setDraft({ ...draft, price_month_cents: Math.round(Number(e.target.value) * 100) })} /></label>
      {LIMITS.map((l) => (
        <label key={l.key} className="saField">{l.label}<input type="number" min={0} placeholder="sem limite" value={draft.limits[l.key] ?? ""}
          onChange={(e) => setDraft({ ...draft, limits: { ...draft.limits, [l.key]: e.target.value === "" ? undefined : Number(e.target.value) } })} /></label>
      ))}
      <div className="saPlanActions">
        {msg ? <small>{msg}</small> : null}
        <button type="button" className="ds-button" disabled={busy} onClick={async () => {
          setBusy(true); setMsg("");
          try { await savePlan(plan.id, { name: draft.name, price_month_cents: draft.price_month_cents, limits: draft.limits }); setMsg("Salvo."); onSaved(); }
          catch (cause) { setMsg(cause instanceof Error ? cause.message : "Erro ao salvar."); } finally { setBusy(false); }
        }}>Salvar plano</button>
      </div>
    </div>
  );
}


function CommercialModuleEditor({ clientId }: { clientId: string }) {
  const [catalog, setCatalog] = useState<CommercialModuleOption[]>([]);
  const [saved, setSaved] = useState<CommercialConfig | null>(null);
  const [draft, setDraft] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [options, current] = await Promise.all([getCommercialCatalog(), getCommercialConfig(clientId)]);
      setCatalog(options.modules);
      setSaved(current.configuration);
      setDraft(current.configuration.module_keys ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Configuração indisponível.");
    } finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void reload(); }, [reload]);

  if (loading) return <p className="saMuted">Carregando módulos…</p>;
  if (error && !saved) return <div role="alert" className="saError">Configuração indisponível: {error} <button type="button" onClick={() => void reload()}>Tentar novamente</button></div>;
  if (!saved) return null;
  const dirty = JSON.stringify([...draft].sort()) !== JSON.stringify([...(saved.module_keys ?? [])].sort()) || !saved.configured;
  const stateLabel = saved.state === "not_configured" ? "Ainda não configurado (comportamento legado)" :
    saved.state === "explicitly_empty" ? "Nenhum módulo opcional contratado" : "Módulos explicitamente selecionados";

  return <div className="saCommercialEditor">
    <p className="saMuted"><strong>{stateLabel}</strong> · Briefing e Tarefas estão sempre incluídos. Social Media inclui Redação.</p>
    <div className="saModuleGrid">
      {catalog.map((item) => <label key={item.key} className="saModuleChoice">
        <input type="checkbox" checked={draft.includes(item.key)} disabled={saving}
          onChange={(event) => setDraft((current) => event.target.checked
            ? [...current, item.key] : current.filter((key) => key !== item.key))} />
        <span>{item.label}</span>
      </label>)}
    </div>
    <div className="saPlanActions">
      {error ? <small role="alert" className="saError">{error}</small> : null}
      <button type="button" className="ds-button" disabled={!dirty || saving || Boolean(error)}
        onClick={async () => {
          setSaving(true); setError("");
          try {
            const result = await saveCommercialConfig(clientId, [...draft].sort(), saved.version);
            setSaved(result.configuration);
            setDraft(result.configuration.module_keys ?? []);
          } catch (cause) {
            setError("Não foi possível salvar. A configuração pode ter sido alterada por outro administrador. Recarregue antes de tentar novamente. " +
              (cause instanceof Error ? cause.message : ""));
          } finally { setSaving(false); }
        }}>{saving ? "Salvando…" : "Salvar módulos"}</button>
      <button type="button" disabled={saving} onClick={() => void reload()}>Recarregar</button>
    </div>
  </div>;
}

/** Painel da equipe Mugô: plano de cada empresa, receita recorrente, faturas em aberto e os planos em si. */
export default function PlansAdmin() {
  const [data, setData] = useState<AdminPlans | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [modulesClient, setModulesClient] = useState<string | null>(null);
  const load = useCallback(() => getAdminPlans().then(setData).catch((cause) => setError(cause instanceof Error ? cause.message : "Não foi possível ler os planos.")), []);
  useEffect(() => { void load(); }, [load]);

  async function setPlan(clientId: string, planId: string, status: SubStatus) {
    setBusy(clientId); setError("");
    try {
      if (!planId) await removeSubscription(clientId);
      else await saveSubscription(clientId, { plan_id: planId, status, trial_days: 14 });
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível salvar."); } finally { setBusy(""); }
  }

  const withPlan = (data?.companies || []).filter((c) => c.subscription).length;
  return (
    <Shell title="Planos e cobrança" variant="editorial">
      <div className="ds-page saPage">
        <PageHeader title="Planos e cobrança" dateline={<span>Empresa sem plano segue sem limite. Faturas saem no dia de cobrança; marque como paga quando receber.</span>} />
        {error ? <p className="saError" role="alert">{error}</p> : null}
        {data ? (
          <>
            <dl className="saKpis">
              <div><dt>Receita recorrente (MRR)</dt><dd>{brl(data.mrr_cents)}</dd></div>
              <div><dt>Empresas com plano</dt><dd>{withPlan} de {data.companies.length}</dd></div>
              <div><dt>Em aberto</dt><dd>{brl(data.companies.reduce((s, c) => s + c.open_cents, 0))}</dd></div>
            </dl>
            <section className="saCard">
              <h2>Empresas</h2>
              <table className="saTable">
                <thead><tr><th>Empresa</th><th>Plano</th><th>Situação</th><th>MRR</th><th>Em aberto</th><th>Módulos</th></tr></thead>
                <tbody>{data.companies.map((c) => (
                  <tr key={c.client_id}>
                    <td><b>{c.name}</b></td>
                    <td><select aria-label={`Plano de ${c.name}`} value={c.subscription?.plan_id || ""} disabled={busy === c.client_id}
                      onChange={(e) => void setPlan(c.client_id, e.target.value, c.subscription?.status || "teste")}>
                      <option value="">Sem plano (sem limite)</option>
                      {data.plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {brl(p.price_month_cents)}</option>)}
                    </select></td>
                    <td>{c.subscription ? <select aria-label={`Situação de ${c.name}`} value={c.subscription.status} disabled={busy === c.client_id}
                      onChange={(e) => void setPlan(c.client_id, c.subscription!.plan_id, e.target.value as SubStatus)}>
                      {(Object.keys(STATUS_LABEL) as SubStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                    </select> : <span className="saMuted">—</span>}</td>
                    <td>{c.mrr_cents ? brl(c.mrr_cents) : "—"}</td>
                    <td>{c.open_cents ? <span className={c.overdue ? "saOverdue" : ""}>{brl(c.open_cents)}{c.overdue ? " · vencida" : ""}</span> : "—"}</td>
                    <td><button type="button" className="ds-button" onClick={() => setModulesClient(modulesClient === c.client_id ? null : c.client_id)} aria-expanded={modulesClient === c.client_id}>Módulos</button></td>
                  </tr>
                ))}</tbody>
              </table>
              {modulesClient ? <div className="saCommercialPanel" key={modulesClient}><h3>Módulos comerciais — {data.companies.find(c => c.client_id === modulesClient)?.name}</h3><CommercialModuleEditor clientId={modulesClient} /></div> : null}
            </section>
            <section className="saCard">
              <h2>Planos</h2>
              <p className="saMuted">Preços e limites editáveis. Limite vazio = sem limite naquele item.</p>
              <div className="saPlans">{data.plans.map((p) => <PlanEditor key={p.id} plan={p} onSaved={() => void load()} />)}</div>
            </section>
          </>
        ) : !error ? <p className="saMuted">Carregando…</p> : null}
      </div>
    </Shell>
  );
}
