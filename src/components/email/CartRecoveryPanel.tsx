import { useCallback, useEffect, useState } from "react";
import { Mail, MessageCircle, Plus, Trash2 } from "lucide-react";
import { formatDateTimeSaoPaulo } from "../../app/dataFormat";
import {
  CART_STATUS_LABEL, CART_VARIABLE_HINT, delayLabel, getCartRecovery, getWaTemplates, previewCartEmail, registerCartWebhooks, saveCartSettings,
  type CartOverview, type CartSettings, type CartStep, type HtmlReport, type WaNumber, type WaTemplate,
} from "../../app/emailMarketing";
import BlockEditor from "./BlockEditor";
import EmailPreview from "./EmailPreview";
import HtmlInput from "./HtmlInput";

const money = (value: number | null | undefined) => Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const DELAYS = [15, 30, 60, 120, 180, 360, 720, 1440, 2880, 4320, 10080];
const WA_VARS: { id: CartSettings["whatsapp_variables"][number]; label: string }[] = [
  { id: "nome", label: "Nome" }, { id: "produto", label: "Produto" }, { id: "valor", label: "Valor" }, { id: "link", label: "Link do carrinho" },
];
const TOUCH_LABEL: Record<string, string> = { enviado: "enviado", simulado: "simulado", pulado: "pulado", falhou: "falhou" };

export default function CartRecoveryPanel({ canEdit }: { canEdit: boolean }) {
  const [data, setData] = useState<CartOverview | null>(null);
  const [settings, setSettings] = useState<CartSettings | null>(null);
  const [wa, setWa] = useState<{ numbers: WaNumber[]; templates: WaTemplate[] } | null>(null);
  const [busy, setBusy] = useState("");
  const [htmlMode, setHtmlMode] = useState<boolean | null>(null);
  const [report, setReport] = useState<HtmlReport | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const out = await getCartRecovery(30);
      setData(out); setSettings(out.settings);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível ler a recuperação de carrinho."); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { getWaTemplates().then(setWa).catch(() => setWa({ numbers: [], templates: [] })); }, []);

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label); setError(""); setMessage("");
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível concluir."); } finally { setBusy(""); }
  }

  if (!data || !settings) return error ? <p className="emError" role="alert">{error}</p> : <p className="emMuted">Carregando carrinhos…</p>;
  if (data.provider !== "shopify") {
    return <section className="emCard"><h2>Carrinho abandonado</h2>
      <p className="emEmpty">A recuperação de carrinho funciona com lojas Shopify{data.provider ? ". Esta empresa usa outra plataforma de loja" : " e esta empresa ainda não tem loja conectada"}.</p></section>;
  }

  const s = data.summary;
  const change = (patch: Partial<CartSettings>) => setSettings({ ...settings, ...patch });
  const setStep = (index: number, patch: Partial<CartStep>) => change({ steps: settings.steps.map((st, i) => (i === index ? { ...st, ...patch } : st)) });
  const hasWa = settings.steps.some((st) => st.channel === "whatsapp");
  const hasEmail = settings.steps.some((st) => st.channel === "email");
  const approved = (wa?.templates || []).filter((t) => t.status === "APPROVED");
  const chosen = approved.find((t) => t.name === settings.whatsapp_template);
  const usingHtml = htmlMode ?? !!settings.email_custom_html;

  return (
    <div className="emCart">
      <dl className="emKpis">
        <div><dt>Carrinhos abandonados</dt><dd>{s.carts.toLocaleString("pt-BR")}</dd><small>{money(s.abandoned_value)} deixados</small></div>
        <div><dt>Contatados</dt><dd>{s.contacted.toLocaleString("pt-BR")}</dd><small>{s.open} em andamento</small></div>
        <div className="is-accent"><dt>Receita recuperada</dt><dd>{money(s.recovered_value)}</dd><small>{s.recovered} pedidos</small></div>
        <div><dt>Taxa de recuperação</dt><dd>{s.recovery_rate == null ? "—" : `${s.recovery_rate.toLocaleString("pt-BR")}%`}</dd><small>dos contatados, últimos 30 dias</small></div>
      </dl>
      <p className="emHint">Recuperado = comprou pelo mesmo checkout até {settings.attribution_days} dias depois de uma mensagem. Quem comprou sem receber nada aparece como “comprou sozinho” ({s.bought_without_contact}) e não entra na receita recuperada.</p>

      {(data.simulated.email && hasEmail) || (data.simulated.whatsapp && hasWa) ? (
        <p className="emNotice">Modo simulado{data.simulated.email && hasEmail ? " no e-mail" : ""}{data.simulated.email && hasEmail && data.simulated.whatsapp && hasWa ? " e" : ""}{data.simulated.whatsapp && hasWa ? " no WhatsApp" : ""}: a sequência roda e registra cada passo, mas nada é enviado até liberar no servidor.</p>
      ) : null}

      <div className="emEditorGrid">
        <div className="emEditorForm">
          <section className="emCard">
            <header className="emCardHead">
              <div>
                <h2>Sequência</h2>
                <p className="emMuted">Contado a partir do abandono. Antes de cada passo o MUGOVERSO confere se a pessoa já comprou.</p>
              </div>
              <label className="emSwitch">
                <input type="checkbox" checked={settings.enabled} disabled={!canEdit} onChange={(e) => change({ enabled: e.target.checked })} />
                <span>{settings.enabled ? "Ligada" : "Desligada"}</span>
              </label>
            </header>
            <ol className="emSteps">
              {settings.steps.map((step, index) => (
                <li key={index} className="emStep">
                  <span className="emStepIcon" aria-hidden="true">{step.channel === "email" ? <Mail size={16} /> : <MessageCircle size={16} />}</span>
                  <select aria-label={`Canal do passo ${index + 1}`} value={step.channel} disabled={!canEdit}
                    onChange={(e) => setStep(index, { channel: e.target.value as CartStep["channel"] })}>
                    <option value="email">E-mail</option>
                    <option value="whatsapp">WhatsApp</option>
                  </select>
                  <span className="emMuted">depois de</span>
                  <select aria-label={`Tempo do passo ${index + 1}`} value={step.delay_minutes} disabled={!canEdit}
                    onChange={(e) => setStep(index, { delay_minutes: Number(e.target.value) })}>
                    {DELAYS.map((d) => <option key={d} value={d}>{delayLabel(d)}</option>)}
                  </select>
                  {canEdit ? <button type="button" className="emIconBtn" aria-label="Remover passo"
                    onClick={() => change({ steps: settings.steps.filter((_, i) => i !== index) })}><Trash2 size={14} /></button> : null}
                </li>
              ))}
            </ol>
            {canEdit && settings.steps.length < 5 ? (
              <button type="button" className="emChip" onClick={() => {
                const last = settings.steps[settings.steps.length - 1]?.delay_minutes || 60;
                change({ steps: [...settings.steps, { channel: "email", delay_minutes: DELAYS.find((d) => d > last) || 10080 }] });
              }}><Plus size={13} aria-hidden="true" /> Passo</button>
            ) : null}
            <p className="emHint">Instagram não entra: a Meta só deixa a marca mandar Direct para quem escreveu nas últimas 24 h, e o checkout não traz o @ da pessoa.</p>
          </section>

          {hasEmail ? (
            <section className="emCard">
              <h3>E-mail do carrinho</h3>
              <label className="emField"><span>Assunto</span>
                <input value={settings.email_subject} disabled={!canEdit} onChange={(e) => change({ email_subject: e.target.value })} /></label>
              <label className="emField"><span>Quem recebe</span>
                <select value={settings.email_consent} disabled={!canEdit} onChange={(e) => change({ email_consent: e.target.value as CartSettings["email_consent"] })}>
                  <option value="todos">Todos que deixaram o e-mail no checkout (lembrete, com descadastro)</option>
                  <option value="consentimento">Só quem aceitou receber marketing</option>
                </select></label>
              <div className="emCardHead">
                <span className="emMuted">Conteúdo</span>
                <div className="ds-segmented" role="group" aria-label="Modo do e-mail do carrinho">
                  <button type="button" aria-pressed={!usingHtml} disabled={!canEdit} onClick={() => { setHtmlMode(false); change({ email_custom_html: null }); }}>Blocos</button>
                  <button type="button" aria-pressed={usingHtml} disabled={!canEdit} onClick={() => setHtmlMode(true)}>HTML próprio</button>
                </div>
              </div>
              {usingHtml ? (
                <HtmlInput value={settings.email_custom_html || ""} disabled={!canEdit} report={report}
                  hint={`Variáveis: ${CART_VARIABLE_HINT} · {{produtos}} insere os itens do carrinho`}
                  onChange={(email_custom_html) => change({ email_custom_html })} />
              ) : (
                <>
                  <p className="emHint">Variáveis: {CART_VARIABLE_HINT}</p>
                  <BlockEditor design={settings.email_design} allowProducts disabled={!canEdit} onChange={(email_design) => change({ email_design })} />
                </>
              )}
            </section>
          ) : null}

          {hasWa ? (
            <section className="emCard">
              <h3>WhatsApp do carrinho</h3>
              {wa && !wa.numbers.some((n) => n.status === "active") ? (
                <p className="emNotice">Esta marca ainda não tem número de WhatsApp ligado ao MUGOVERSO (Integrações → WhatsApp). Sem ele, o passo de WhatsApp é pulado.</p>
              ) : null}
              <label className="emField"><span>Template aprovado pela Meta</span>
                <select value={settings.whatsapp_template || ""} disabled={!canEdit}
                  onChange={(e) => {
                    const t = approved.find((x) => x.name === e.target.value);
                    change({ whatsapp_template: e.target.value || null, whatsapp_language: t?.language || "pt_BR" });
                  }}>
                  <option value="">Escolha…</option>
                  {approved.map((t) => <option key={`${t.name}:${t.language}`} value={t.name}>{t.name} ({t.category.toLowerCase()})</option>)}
                </select></label>
              {chosen ? <blockquote className="emTemplateBody">{chosen.body}</blockquote> : null}
              <div className="emField"><span>O que vai em cada variável do template, na ordem</span>
                <div className="emVarRow">
                  {settings.whatsapp_variables.map((v, i) => (
                    <select key={i} aria-label={`Variável ${i + 1}`} value={v} disabled={!canEdit}
                      onChange={(e) => change({ whatsapp_variables: settings.whatsapp_variables.map((x, j) => (j === i ? e.target.value as typeof v : x)) })}>
                      {WA_VARS.map((o) => <option key={o.id} value={o.id}>{`{{${i + 1}}}`} {o.label}</option>)}
                    </select>
                  ))}
                  {canEdit && settings.whatsapp_variables.length < 4 ? (
                    <button type="button" className="emChip" onClick={() => change({ whatsapp_variables: [...settings.whatsapp_variables, "link"] })}>+ variável</button>
                  ) : null}
                  {canEdit && settings.whatsapp_variables.length ? (
                    <button type="button" className="emChip" onClick={() => change({ whatsapp_variables: settings.whatsapp_variables.slice(0, -1) })}>− variável</button>
                  ) : null}
                </div>
                {chosen && chosen.variables !== settings.whatsapp_variables.length ? (
                  <small className="emWarn">O template tem {chosen.variables} variável(is); aqui estão {settings.whatsapp_variables.length}.</small>
                ) : null}
              </div>
              <label className="emField"><span>Quem recebe</span>
                <select value={settings.whatsapp_consent} disabled={!canEdit} onChange={(e) => change({ whatsapp_consent: e.target.value as CartSettings["whatsapp_consent"] })}>
                  <option value="consentimento">Só quem aceitou receber marketing no checkout</option>
                  <option value="consentimento_ou_conversa">Também quem já conversou com a marca no WhatsApp</option>
                </select></label>
            </section>
          ) : null}

          {error ? <p className="emError" role="alert">{error}</p> : null}
          {message ? <p className="emOk">{message}</p> : null}
          {canEdit ? (
            <div className="emActions">
              <button type="button" className="ds-button" disabled={!!busy}
                onClick={() => void run("hooks", async () => {
                  const out = await registerCartWebhooks();
                  setMessage(out.failed.length ? `A Shopify recusou: ${out.failed.map((f) => f.topic).join(", ")}.` : "Aviso de checkout ligado na Shopify.");
                  await load();
                })}>{busy === "hooks" ? "Ligando…" : settings.webhooks_registered_at ? "Religar aviso de checkout" : "Ligar aviso de checkout na Shopify"}</button>
              <button type="button" className="ds-button is-primary" disabled={!!busy}
                onClick={() => void run("save", async () => { setSettings((await saveCartSettings(settings)).settings); setMessage("Recuperação de carrinho salva."); })}>
                {busy === "save" ? "Salvando…" : "Salvar"}</button>
            </div>
          ) : null}
        </div>

        {hasEmail ? (
          <EmailPreview deps={[settings.email_design, settings.email_subject, usingHtml ? settings.email_custom_html : null]} onReport={setReport}
            load={() => previewCartEmail(settings.email_design, settings.email_subject, usingHtml ? settings.email_custom_html : null)} />
        ) : <div />}
      </div>

      <section className="emCard">
        <h2>Últimos carrinhos</h2>
        {data.recent.length === 0 ? <p className="emEmpty">Nenhum carrinho abandonado nos últimos 30 dias{settings.webhooks_registered_at ? "" : " (o aviso de checkout ainda não foi ligado)"}.</p> : (
          <div className="emTableWrap">
            <table className="emTable">
              <thead><tr><th>Quando</th><th>Itens</th><th>Valor</th><th>Último contato</th><th>Situação</th></tr></thead>
              <tbody>
                {data.recent.map((c) => (
                  <tr key={c.checkout_id}>
                    <td>{c.created_at ? formatDateTimeSaoPaulo(c.created_at) : "—"}</td>
                    <td>{c.first_item || "—"}{c.items > 1 ? <small> + {c.items - 1}</small> : null}</td>
                    <td>{money(c.value)}</td>
                    <td>{c.last_touch ? `${c.last_touch.channel === "email" ? "E-mail" : "WhatsApp"} · ${TOUCH_LABEL[c.last_touch.status]}${c.last_touch.reason ? ` (${c.last_touch.reason})` : ""}` : "—"}</td>
                    <td><span className={`emPill is-${c.status}`}>{CART_STATUS_LABEL[c.status]}</span>{c.recovered_value ? <small> {money(c.recovered_value)}</small> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
