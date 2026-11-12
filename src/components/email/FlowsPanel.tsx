import { useEffect, useState } from "react";
import { Gift, HeartHandshake, Repeat, Sparkles } from "lucide-react";
import {
  FLOW_HELP, getFlows, getWaTemplates, previewFlow, saveFlow, VARIABLE_HINT,
  type CommercialFlow, type FlowKind, type FlowsOverview, type HtmlReport, type WaTemplate,
} from "../../app/emailMarketing";
import BlockEditor from "./BlockEditor";
import EmailPreview from "./EmailPreview";
import HtmlInput from "./HtmlInput";

const ICON: Record<FlowKind, typeof Gift> = { boas_vindas: Gift, pos_venda: HeartHandshake, segunda_compra: Repeat, reativacao: Sparkles };
const money = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const WA_VARS = [{ id: "nome", label: "Nome" }, { id: "marca", label: "Marca" }, { id: "link", label: "Link da loja" }] as const;

function FlowEditor({ flow, canEdit, templates, onSaved }: {
  flow: CommercialFlow; canEdit: boolean; templates: WaTemplate[]; onSaved: (flow: CommercialFlow) => void;
}) {
  const [draft, setDraft] = useState(flow);
  const [html, setHtml] = useState(!!flow.custom_html);
  const [report, setReport] = useState<HtmlReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const change = (patch: Partial<CommercialFlow>) => setDraft((d) => ({ ...d, ...patch }));
  const approved = templates.filter((t) => t.status === "APPROVED");
  const chosen = approved.find((t) => t.name === draft.whatsapp_template);

  async function save(patch: Partial<CommercialFlow> = {}) {
    setBusy(true); setError(""); setMessage("");
    const next = { ...draft, ...patch, custom_html: html ? draft.custom_html || "" : null };
    try {
      const out = await saveFlow(flow.kind, next);
      setDraft({ ...out.flow, result: flow.result }); onSaved({ ...out.flow, result: flow.result });
      setMessage(out.flow.enabled ? "Fluxo ligado e salvo." : "Fluxo salvo.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível salvar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="emFlowEditor">
      <div className="emEditorGrid">
        <div className="emEditorForm">
          <div className="emFlowRow">
            <label className="emField"><span>Canal</span>
              <select value={draft.channel} disabled={!canEdit} onChange={(e) => change({ channel: e.target.value as CommercialFlow["channel"] })}>
                <option value="email">E-mail</option><option value="whatsapp">WhatsApp</option>
              </select></label>
            <label className="emField"><span>Quando</span>
              <span className="emInline"><input type="number" min={0} max={365} value={draft.delay_days} disabled={!canEdit}
                onChange={(e) => change({ delay_days: Number(e.target.value) })} /> {FLOW_HELP[flow.kind].delay}</span></label>
            <label className="emField"><span>Quem recebe</span>
              <select value={draft.consent} disabled={!canEdit} onChange={(e) => change({ consent: e.target.value as CommercialFlow["consent"] })}>
                <option value="consentimento">Só quem aceitou marketing</option>
                <option value="todos">{draft.channel === "email" ? "Todos (com descadastro)" : "Aceitou marketing ou já conversou no WhatsApp"}</option>
              </select></label>
          </div>
          {draft.channel === "email" ? (
            <>
              <label className="emField"><span>Assunto</span><input value={draft.subject} disabled={!canEdit} onChange={(e) => change({ subject: e.target.value })} /></label>
              <label className="emField"><span>Pré-cabeçalho</span><input value={draft.preheader} disabled={!canEdit} onChange={(e) => change({ preheader: e.target.value })} /></label>
              <div className="emCardHead">
                <span className="emMuted">Conteúdo</span>
                <div className="ds-segmented" role="group" aria-label="Modo do e-mail do fluxo">
                  <button type="button" aria-pressed={!html} disabled={!canEdit} onClick={() => setHtml(false)}>Blocos</button>
                  <button type="button" aria-pressed={html} disabled={!canEdit} onClick={() => setHtml(true)}>HTML próprio</button>
                </div>
              </div>
              {html ? (
                <HtmlInput value={draft.custom_html || ""} disabled={!canEdit} report={report} hint={`Variáveis: ${VARIABLE_HINT}`}
                  onChange={(custom_html) => change({ custom_html })} />
              ) : (
                <BlockEditor design={draft.design} disabled={!canEdit} onChange={(design) => change({ design })} />
              )}
            </>
          ) : (
            <>
              <label className="emField"><span>Template aprovado pela Meta</span>
                <select value={draft.whatsapp_template || ""} disabled={!canEdit}
                  onChange={(e) => change({ whatsapp_template: e.target.value || null, whatsapp_language: approved.find((t) => t.name === e.target.value)?.language || "pt_BR" })}>
                  <option value="">Escolha…</option>
                  {approved.map((t) => <option key={`${t.name}:${t.language}`} value={t.name}>{t.name}</option>)}
                </select></label>
              {chosen ? <blockquote className="emTemplateBody">{chosen.body}</blockquote> : null}
              {!approved.length ? <p className="emNotice">Nenhum template aprovado nesta marca. Crie no WhatsApp Manager da conta Meta dela.</p> : null}
              <div className="emVarRow">
                {draft.whatsapp_variables.map((v, i) => (
                  <select key={i} aria-label={`Variável ${i + 1}`} value={v} disabled={!canEdit}
                    onChange={(e) => change({ whatsapp_variables: draft.whatsapp_variables.map((x, j) => (j === i ? e.target.value as typeof v : x)) })}>
                    {WA_VARS.map((o) => <option key={o.id} value={o.id}>{`{{${i + 1}}}`} {o.label}</option>)}
                  </select>
                ))}
                {canEdit && draft.whatsapp_variables.length < 3 ? <button type="button" className="emChip" onClick={() => change({ whatsapp_variables: [...draft.whatsapp_variables, "link"] })}>+ variável</button> : null}
                {canEdit && draft.whatsapp_variables.length ? <button type="button" className="emChip" onClick={() => change({ whatsapp_variables: draft.whatsapp_variables.slice(0, -1) })}>− variável</button> : null}
              </div>
            </>
          )}
          {error ? <p className="emError" role="alert">{error}</p> : null}
          {canEdit ? (
            <div className="emActions">
              {message ? <span className="emOk">{message}</span> : null}
              <button type="button" className="ds-button" disabled={busy} onClick={() => void save()}>Salvar</button>
              <button type="button" className={`ds-button${draft.enabled ? "" : " is-primary"}`} disabled={busy}
                onClick={() => void save({ enabled: !draft.enabled })}>{draft.enabled ? "Desligar fluxo" : "Salvar e ligar"}</button>
            </div>
          ) : null}
        </div>
        {draft.channel === "email" ? (
          <EmailPreview deps={[draft.subject, draft.preheader, draft.design, html ? draft.custom_html : null]} onReport={setReport}
            load={() => previewFlow(flow.kind, { ...draft, custom_html: html ? draft.custom_html : null })} />
        ) : <div />}
      </div>
    </div>
  );
}

export default function FlowsPanel({ canEdit }: { canEdit: boolean }) {
  const [data, setData] = useState<FlowsOverview | null>(null);
  const [open, setOpen] = useState<FlowKind | null>(null);
  const [templates, setTemplates] = useState<WaTemplate[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getFlows(30).then(setData).catch((cause) => setError(cause instanceof Error ? cause.message : "Não foi possível ler os fluxos."));
    getWaTemplates().then((out) => setTemplates(out.templates)).catch(() => setTemplates([]));
  }, []);

  if (!data) return error ? <p className="emError" role="alert">{error}</p> : <p className="emMuted">Carregando fluxos…</p>;
  const replace = (flow: CommercialFlow) => setData({ ...data, flows: data.flows.map((f) => (f.kind === flow.kind ? flow : f)) });

  return (
    <div className="emCart">
      <section className="emCard">
        <header className="emCardHead">
          <div>
            <h2>Fluxos automáticos</h2>
            <p className="emMuted">Mensagens que saem sozinhas quando o cliente cruza um marco. Só quem está cruzando agora recebe: ligar não dispara para a base inteira.</p>
          </div>
        </header>
        {!data.journey_built_at ? <p className="emNotice">A medição de quem comprou depois da mensagem começa assim que a jornada do cliente for montada (automático, toda madrugada).</p> : null}
        <div className="emFlows">
          {data.flows.map((flow) => {
            const Icon = ICON[flow.kind];
            const r = flow.result;
            return (
              <article key={flow.kind} className={`emFlow${flow.enabled ? " is-on" : ""}`}>
                <div className="emFlowHead">
                  <span className="emStepIcon" aria-hidden="true"><Icon size={16} /></span>
                  <div className="emFlowTitle">
                    <strong>{flow.label}</strong>
                    <small>{FLOW_HELP[flow.kind].when} · {flow.delay_days} {FLOW_HELP[flow.kind].delay} · {flow.channel === "email" ? "E-mail" : "WhatsApp"}</small>
                  </div>
                  <span className={`emPill ${flow.enabled ? "is-ok" : ""}`}>{flow.enabled ? "Ligado" : "Desligado"}</span>
                </div>
                <dl className="emFlowStats">
                  <div><dt>Enviados</dt><dd>{r.sent.toLocaleString("pt-BR")}</dd></div>
                  <div><dt>Compraram</dt><dd>{r.buyers.toLocaleString("pt-BR")}</dd></div>
                  <div><dt>Receita</dt><dd>{money(r.revenue)}</dd></div>
                  <div><dt>Conversão</dt><dd>{r.conversion == null ? "—" : `${r.conversion.toLocaleString("pt-BR")}%`}</dd></div>
                </dl>
                <button type="button" className="emLink" onClick={() => setOpen(open === flow.kind ? null : flow.kind)}>
                  {open === flow.kind ? "Fechar" : canEdit ? "Configurar mensagem" : "Ver mensagem"}
                </button>
                {open === flow.kind ? <FlowEditor flow={flow} canEdit={canEdit} templates={templates} onSaved={replace} /> : null}
              </article>
            );
          })}
        </div>
        <p className="emHint">“Compraram” conta quem recebeu a mensagem e comprou em até 7 dias (olhando os últimos 30 dias). Cada pedido conta uma vez por fluxo.
          {data.simulated.email || data.simulated.whatsapp ? " Em modo simulado os envios são registrados, mas não saem." : ""}</p>
      </section>
    </div>
  );
}
