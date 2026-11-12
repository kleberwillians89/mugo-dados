import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Plus } from "lucide-react";
import { formatDateTimeSaoPaulo } from "../../app/dataFormat";
import {
  cancelCampaign, createCampaign, deleteCampaign, getCampaign, listCampaigns, previewAudience, previewEmail, scheduleCampaign,
  SEGMENT_LABEL, sendTestEmail, STATUS_LABEL, updateCampaign, VARIABLE_HINT,
  type Audience, type AudiencePreview, type Campaign, type CampaignStats, type CampaignSummary, type HtmlReport, type Segment,
} from "../../app/emailMarketing";
import BlockEditor from "./BlockEditor";
import EmailPreview from "./EmailPreview";
import HtmlInput from "./HtmlInput";

const pct = (value: number | null | undefined) => (value == null ? "—" : `${value.toLocaleString("pt-BR")}%`);
const int = (value: number | null | undefined) => Number(value || 0).toLocaleString("pt-BR");

function StatsRow({ stats }: { stats: Partial<CampaignStats> | null | undefined }) {
  if (!stats || stats.sent == null) return null;
  return (
    <dl className="emStats">
      <div><dt>Enviados</dt><dd>{int(stats.sent)}</dd></div>
      <div><dt>Entregues</dt><dd>{int(stats.delivered)}</dd></div>
      <div><dt>Abertura</dt><dd>{pct(stats.open_rate)}</dd></div>
      <div><dt>Cliques</dt><dd>{pct(stats.click_rate)}</dd></div>
      <div><dt>Bounces</dt><dd>{int(stats.bounced)}</dd></div>
      {stats.simulated ? <div><dt>Simulados</dt><dd>{int(stats.simulated)}</dd></div> : null}
    </dl>
  );
}

export function CampaignEditor({ id, canEdit, onBack }: { id: string; canEdit: boolean; onBack: () => void }) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [stats, setStats] = useState<CampaignStats | null>(null);
  const [mode, setMode] = useState<"blocos" | "html">("blocos");
  const [audience, setAudience] = useState<AudiencePreview | null>(null);
  const [report, setReport] = useState<HtmlReport | null>(null);
  const [testTo, setTestTo] = useState("");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    getCampaign(id).then((out) => {
      if (!alive) return;
      setCampaign(out.campaign); setStats(out.stats); setMode(out.campaign.custom_html ? "html" : "blocos");
    }).catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "Campanha não encontrada."); });
    return () => { alive = false; };
  }, [id]);

  const editable = canEdit && !!campaign && ["rascunho", "agendada"].includes(campaign.status);
  const change = (patch: Partial<Campaign>) => setCampaign((current) => (current ? { ...current, ...patch } : current));
  const setAud = (patch: Partial<Audience>) => campaign && change({ audience: { ...campaign.audience, ...patch } });

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label); setError(""); setMessage("");
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível concluir."); } finally { setBusy(""); }
  }
  const payload = () => campaign && {
    name: campaign.name, subject: campaign.subject, preheader: campaign.preheader, design: campaign.design, audience: campaign.audience,
    custom_html: mode === "html" ? campaign.custom_html || "" : null,
  };
  const save = () => run("save", async () => {
    const out = await updateCampaign(id, payload()!);
    setCampaign(out.campaign); setMessage("Campanha salva.");
  });

  if (!campaign) return error ? <p className="emError" role="alert">{error}</p> : <p className="emMuted">Abrindo campanha…</p>;
  return (
    <div className="emEditor">
      <div className="emEditorTop">
        <button type="button" className="ds-button" onClick={onBack}><ArrowLeft size={15} aria-hidden="true" /> Campanhas</button>
        <span className={`emPill is-${campaign.status}`}>{STATUS_LABEL[campaign.status]}</span>
      </div>
      <div className="emEditorGrid">
        <div className="emEditorForm">
          <section className="emCard">
            <label className="emField"><span>Nome interno</span>
              <input value={campaign.name} disabled={!editable} onChange={(e) => change({ name: e.target.value })} /></label>
            <label className="emField"><span>Assunto</span>
              <input value={campaign.subject} disabled={!editable} placeholder="Ex.: {{primeiro_nome}}, chegou a coleção nova" onChange={(e) => change({ subject: e.target.value })} /></label>
            <label className="emField"><span>Pré-cabeçalho</span>
              <input value={campaign.preheader} disabled={!editable} placeholder="Texto curto que aparece depois do assunto na caixa de entrada" onChange={(e) => change({ preheader: e.target.value })} /></label>
            <p className="emHint">Variáveis: {VARIABLE_HINT}</p>
          </section>

          <section className="emCard">
            <header className="emCardHead">
              <h3>Conteúdo</h3>
              <div className="ds-segmented" role="group" aria-label="Modo de edição">
                <button type="button" aria-pressed={mode === "blocos"} onClick={() => setMode("blocos")} disabled={!editable}>Blocos</button>
                <button type="button" aria-pressed={mode === "html"} onClick={() => setMode("html")} disabled={!editable}>HTML próprio</button>
              </div>
            </header>
            {mode === "blocos" ? (
              <BlockEditor design={campaign.design} disabled={!editable} onChange={(design) => change({ design })} />
            ) : (
              <HtmlInput value={campaign.custom_html || ""} disabled={!editable} report={report} hint={`Variáveis: ${VARIABLE_HINT}`}
                onChange={(custom_html) => change({ custom_html })} />
            )}
          </section>

          <section className="emCard">
            <h3>Para quem</h3>
            <div className="emAudience">
              <select aria-label="Público" value={campaign.audience.segment} disabled={!editable}
                onChange={(e) => setAud({ segment: e.target.value as Segment, only_consent: e.target.value !== "todos" })}>
                {(Object.keys(SEGMENT_LABEL) as Segment[]).map((s) => <option key={s} value={s}>{SEGMENT_LABEL[s]}</option>)}
              </select>
              {["compraram", "sem_compra"].includes(campaign.audience.segment) ? (
                <label className="emInline">há <input type="number" min={1} max={730} value={campaign.audience.days} disabled={!editable}
                  onChange={(e) => setAud({ days: Number(e.target.value) || 90 })} /> dias</label>
              ) : null}
              {campaign.audience.segment !== "consentimento" ? (
                <label className="emInline"><input type="checkbox" checked={campaign.audience.only_consent} disabled={!editable}
                  onChange={(e) => setAud({ only_consent: e.target.checked })} /> Só quem aceitou receber e-mails</label>
              ) : null}
              {canEdit ? (
                <button type="button" className="ds-button" disabled={!!busy}
                  onClick={() => void run("audience", async () => setAudience(await previewAudience(campaign.audience)))}>
                  {busy === "audience" ? "Contando…" : "Contar público"}</button>
              ) : null}
            </div>
            {audience ? (
              <p className="emAudienceCount"><strong>{int(audience.count)}</strong> pessoas recebem · base com e-mail {int(audience.base)}
                {audience.consent_known ? ` · ${int(audience.with_consent)} aceitaram marketing` : " · a loja não informa consentimento"}
                {audience.blocked ? ` · ${int(audience.blocked)} descadastrados/bounce ficam de fora` : ""}</p>
            ) : null}
            {!campaign.audience.only_consent ? (
              <p className="emNotice">Enviar para quem não aceitou receber e-mails é responsabilidade da marca (LGPD). O descadastro em 1 clique vai em todos.</p>
            ) : null}
          </section>

          {error ? <p className="emError" role="alert">{error}</p> : null}
          {message ? <p className="emOk">{message}</p> : null}

          {editable ? (
            <section className="emCard emSendBox">
              <div className="emInlineRow">
                <input type="email" aria-label="E-mail para teste" placeholder="seu@email.com" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
                <button type="button" className="ds-button" disabled={!!busy || !testTo}
                  onClick={() => void run("test", async () => {
                    await updateCampaign(id, payload()!);
                    const out = await sendTestEmail(id, testTo);
                    setMessage(out.status === "simulado" ? "Teste registrado (modo simulado: nada saiu)." : `Teste enviado para ${testTo}.`);
                  })}>{busy === "test" ? "Enviando…" : "Enviar teste"}</button>
              </div>
              <div className="emInlineRow">
                <input type="datetime-local" aria-label="Agendar para" value={when} onChange={(e) => setWhen(e.target.value)} />
                <button type="button" className="ds-button is-primary" disabled={!!busy}
                  onClick={() => void run("send", async () => {
                    await updateCampaign(id, payload()!);
                    const at = when ? new Date(when).toISOString() : null;
                    const out = await scheduleCampaign(id, at);
                    setCampaign(out.campaign);
                    setMessage(at ? "Campanha agendada." : "Campanha na fila: o envio começa em até 5 minutos.");
                  })}>{busy === "send" ? "Confirmando…" : when ? "Agendar envio" : "Enviar agora"}</button>
                <button type="button" className="ds-button" disabled={!!busy} onClick={() => void save()}>{busy === "save" ? "Salvando…" : "Salvar"}</button>
              </div>
            </section>
          ) : null}
          {canEdit && ["agendada", "enviando"].includes(campaign.status) ? (
            <button type="button" className="ds-button is-danger" disabled={!!busy}
              onClick={() => void run("cancel", async () => setCampaign((await cancelCampaign(id)).campaign))}>Cancelar envio</button>
          ) : null}
          <StatsRow stats={stats || campaign.stats} />
        </div>

        <EmailPreview deps={[campaign.subject, campaign.preheader, campaign.design, mode, campaign.custom_html]}
          load={() => previewEmail({ ...payload()! })} onReport={setReport} />
      </div>
    </div>
  );
}

export default function CampaignsPanel({ canEdit }: { canEdit: boolean }) {
  const [list, setList] = useState<CampaignSummary[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => listCampaigns().then((out) => setList(out.campaigns))
    .catch((cause) => setError(cause instanceof Error ? cause.message : "Não foi possível ler as campanhas.")), []);
  useEffect(() => { if (!open) void load(); }, [open, load]);

  if (open) return <CampaignEditor id={open} canEdit={canEdit} onBack={() => setOpen(null)} />;
  return (
    <section className="emCard">
      <header className="emCardHead">
        <div>
          <h2>Campanhas</h2>
          <p className="emMuted">Monte o e-mail por blocos (ou cole seu HTML), escolha o público e envie pelo Resend.</p>
        </div>
        {canEdit ? (
          <button type="button" className="ds-button is-primary" onClick={async () => {
            try { setOpen((await createCampaign({})).campaign.id); } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível criar."); }
          }}><Plus size={15} aria-hidden="true" /> Nova campanha</button>
        ) : null}
      </header>
      {error ? <p className="emError" role="alert">{error}</p> : null}
      {list && list.length === 0 ? <p className="emEmpty">Nenhuma campanha ainda.</p> : null}
      {list && list.length ? (
        <div className="emTableWrap">
          <table className="emTable">
            <thead><tr><th>Campanha</th><th>Status</th><th>Envio</th><th>Enviados</th><th>Abertura</th><th>Cliques</th><th /></tr></thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td><button type="button" className="emLink" onClick={() => setOpen(c.id)}>{c.name}</button><small>{c.subject || "Sem assunto"}</small></td>
                  <td><span className={`emPill is-${c.status}`}>{STATUS_LABEL[c.status]}</span></td>
                  <td>{c.finished_at || c.scheduled_at ? formatDateTimeSaoPaulo((c.finished_at || c.scheduled_at)!) : "—"}</td>
                  <td>{c.stats?.sent != null ? int(c.stats.sent) : "—"}</td>
                  <td>{pct(c.stats?.open_rate)}</td>
                  <td>{pct(c.stats?.click_rate)}</td>
                  <td>{canEdit && c.status === "rascunho" ? (
                    <button type="button" className="emLink is-danger" onClick={async () => { await deleteCampaign(c.id); await load(); }}>Apagar</button>
                  ) : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
