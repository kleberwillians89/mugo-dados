import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  createWhatsAppCampaignDraft, listWhatsAppCampaignDrafts, listWhatsAppTemplates,
  getWhatsAppContactImportStatus, importExistingCommerceContacts, importExistingWhatsAppConversations,
  preflightWhatsAppCampaignTemplate, previewWhatsAppCampaignAudience, sendWhatsAppCampaign,
  type WaCampaignAudience, type WaCampaignDraft, type WaTemplate, type WaContactImportStatus,
} from "../../app/whatsapp";
import "./WhatsAppBulkCampaigns.css";

type Provider = "all" | "shopify" | "fbits" | "whatsapp" | "capture";
const SOURCES: { value: Provider; title: string }[] = [
  { value: "all", title: "Todas as origens" },
  { value: "shopify", title: "Shopify" },
  { value: "fbits", title: "Wake / FBITS" },
  { value: "whatsapp", title: "Conversas WhatsApp" },
  { value: "capture", title: "Captação / Landing Pages (First Access)" },
];
const fmt = (n: number) => new Intl.NumberFormat("pt-BR").format(n);
const STATUS: Record<WaCampaignDraft["status"], string> = {
  draft: "Pronta para enviar", sending: "Enviando…", sent: "Enviada", partial: "Enviada em parte", failed: "Falhou",
};

export default function WhatsAppBulkCampaigns() {
  const tenant = getActiveClientId();
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<Provider>("all");
  const [templateKey, setTemplateKey] = useState("");
  const [templates, setTemplates] = useState<WaTemplate[]>([]);
  const [audience, setAudience] = useState<WaCampaignAudience | null>(null);
  const [drafts, setDrafts] = useState<WaCampaignDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preflight, setPreflight] = useState<{ approved: boolean; note: string } | null>(null);
  const [importBusy, setImportBusy] = useState<"commerce" | "whatsapp" | null>(null);
  const [importStatus, setImportStatus] = useState<WaContactImportStatus | null>(null);
  const [importNote, setImportNote] = useState("");
  const [importError, setImportError] = useState("");
  const [draftsError, setDraftsError] = useState("");
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<WaCampaignDraft | null>(null);

  const approved = useMemo(() => templates.filter((t) => t.status.toUpperCase() === "APPROVED"), [templates]);
  const selected = approved.find((t) => `${t.name}::${t.language}` === templateKey);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [templateResponse, draftResponse] = await Promise.allSettled([
      listWhatsAppTemplates(), listWhatsAppCampaignDrafts(),
    ]);
    if (getActiveClientId() !== tenant) return;
    if (templateResponse.status === "fulfilled") setTemplates(templateResponse.value.templates);
    else setError("Não foi possível carregar os modelos da empresa.");
    if (draftResponse.status === "fulfilled") setDrafts(draftResponse.value.drafts);
    else setDraftsError("Histórico indisponível. Verifique se a migration 000120 foi aplicada no Supabase.");
    if (draftResponse.status === "fulfilled") setDraftsError("");
    setLoading(false);
  }, [tenant]);

  useEffect(() => {
    let active = true;
    setTemplates([]); setDrafts([]); setTemplateKey(""); setName(""); setPreflight(null);
    setError(""); setNotice(""); setLoading(true);
    setImportStatus(null); setImportNote(""); setImportError(""); setDraftsError("");
    Promise.allSettled([listWhatsAppTemplates(), listWhatsAppCampaignDrafts()]).then(([t, d]) => {
      if (!active || getActiveClientId() !== tenant) return;
      if (t.status === "fulfilled") setTemplates(t.value.templates);
      else setError("Modelos WhatsApp indisponíveis nesta empresa.");
      if (d.status === "fulfilled") setDrafts(d.value.drafts);
      else setDraftsError("Histórico indisponível. Verifique se a migration 000120 foi aplicada no Supabase.");
      setLoading(false);
    });
    return () => { active = false; };
  }, [tenant]);

  const anySending = drafts.some((d) => d.status === "sending");
  useEffect(() => {
    if (!anySending) return;
    const timer = window.setInterval(() => {
      listWhatsAppCampaignDrafts().then((r) => { if (getActiveClientId() === tenant) setDrafts(r.drafts); }).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [anySending, tenant]);

  async function send(draft: WaCampaignDraft) {
    setConfirming(null); setSendingId(draft.id); setError(""); setNotice("");
    try {
      const r = await sendWhatsAppCampaign(draft.id);
      if (getActiveClientId() !== tenant) return;
      setNotice(`Envio começou para ${fmt(r.recipients_count)} contatos. Acompanhe no histórico.`);
      await refresh();
    } catch (cause) {
      if (getActiveClientId() === tenant) setError(cause instanceof Error ? cause.message : "Não foi possível começar o envio.");
    } finally { setSendingId(null); }
  }

  useEffect(() => {
    let active = true;
    getWhatsAppContactImportStatus().then((status) => {
      if (active && getActiveClientId() === tenant) setImportStatus(status);
    }).catch(() => {
      if (active && getActiveClientId() === tenant) setImportError("Não foi possível consultar o status da base de contatos.");
    });
    return () => { active = false; };
  }, [tenant]);

  async function importContacts(source: "commerce" | "whatsapp") {
    if (importBusy) return;
    setImportBusy(source); setImportError(""); setImportNote("");
    const selectedTenant = tenant;
    try {
      const result = source === "commerce"
        ? await importExistingCommerceContacts()
        : await importExistingWhatsAppConversations(365);
      if (getActiveClientId() !== selectedTenant) return;
      setImportNote(`${new Intl.NumberFormat("pt-BR").format(result.contacts_synchronized)} contatos sincronizados de ${result.provider}. Nenhuma mensagem foi enviada.`);
      const [status, currentAudience] = await Promise.all([
        getWhatsAppContactImportStatus(), previewWhatsAppCampaignAudience(provider),
      ]);
      if (getActiveClientId() !== selectedTenant) return;
      setImportStatus(status); setAudience(currentAudience);
    } catch (cause) {
      if (getActiveClientId() === selectedTenant) {
        setImportError(cause instanceof Error ? cause.message : "Importação não concluída. Confira o conector da empresa.");
      }
    } finally { setImportBusy(null); }
  }

  useEffect(() => {
    let active = true;
    setAudience(null);
    setPreflight(null);
    previewWhatsAppCampaignAudience(provider).then((result) => {
      if (active && getActiveClientId() === tenant) setAudience(result);
    }).catch(() => {
      if (active && getActiveClientId() === tenant) setError("Não foi possível consultar o público. Verifique a migration 000119 e a conexão.");
    });
    return () => { active = false; };
  }, [tenant, provider]);

  async function simulate(event: FormEvent) {
    event.preventDefault();
    if (!selected || busy) return;
    setBusy(true); setError(""); setNotice(""); setPreflight(null);
    try {
      const t = await preflightWhatsAppCampaignTemplate(selected.name, selected.language);
      if (getActiveClientId() !== tenant) return;
      setPreflight({ approved: t.template_approved, note: t.template_approved
        ? "Modelo aprovado. A campanha foi salva no histórico: clique em Enviar para disparar."
        : "O modelo não está aprovado na Meta. Selecione outro modelo." });
      if (!t.template_approved) return;
      const response = await createWhatsAppCampaignDraft({
        name: name.trim(), template_name: selected.name, language: selected.language, provider,
      });
      if (getActiveClientId() !== tenant) return;
      setNotice(`Campanha "${response.draft.name}" pronta. Confira no histórico e clique em Enviar.`);
      await refresh();
    } catch (cause) {
      if (getActiveClientId() === tenant) setError(cause instanceof Error ? cause.message : "Não foi possível simular a campanha.");
    } finally { setBusy(false); }
  }

  return <div className="waBulk">
    <header className="waBulkHeading">
      <div>
        <h2>Disparos em massa</h2>
        <p>Monte a campanha com um modelo aprovado pela Meta e envie para a base da empresa selecionada.</p>
      </div>
      <span className="waBulkChip is-on">Envio liberado</span>
    </header>
    <section className="waBulkPanel waBulkImport" aria-label="Importar contatos existentes">
      <div className="waBulkHistoryHead"><div>
        <h3>Importar contatos existentes</h3>
        <p className="waBulkHelp">A importação aproveita dados já sincronizados da empresa selecionada, sem CSV nem token manual. Não envia mensagens nem presume consentimento.</p>
      </div></div>
      <div className="waBulkImportActions">
        <button type="button" onClick={() => void importContacts("commerce")} disabled={!!importBusy}>
          {importBusy === "commerce" ? "Importando clientes..." : "Importar clientes da loja"}
        </button>
        <button type="button" onClick={() => void importContacts("whatsapp")} disabled={!!importBusy}>
          {importBusy === "whatsapp" ? "Importando conversas..." : "Importar conversas WhatsApp"}
        </button>
      </div>
      {importStatus ? <p className="waBulkHelp" role="status">
        Base atual: {fmt(importStatus.total)} perfis · Shopify: {fmt(importStatus.by_provider.shopify || 0)}
        {" · "}Wake/FBITS: {fmt(importStatus.by_provider.fbits || 0)}
        {" · "}WhatsApp: {fmt(importStatus.by_provider.whatsapp || 0)}
        {importStatus.truncated ? " · Contagem parcial" : ""}
      </p> : null}
      {importNote ? <p className="waBulkSuccess" role="status">{importNote}</p> : null}
      {importError ? <p className="waBulkError" role="alert">{importError}</p> : null}
    </section>
    <div className="waBulkStats" aria-label="Resumo da audiência WhatsApp">
      <div><small>Contatos na base</small><strong>{audience ? fmt(audience.total_contacts) : "—"}</strong></div>
      <div><small>Consentimento WA verificado</small><strong>{audience ? fmt(audience.consent_verified_count) : "—"}</strong></div>
      <div><small>Recebem nesta origem</small><strong>{audience ? fmt(audience.sendable_count) : "—"}</strong></div>
      <div><small>Campanhas em rascunho</small><strong>{fmt(drafts.length)}</strong></div>
    </div>
    <div className="waBulkColumns">
      <form className="waBulkPanel" onSubmit={(event) => void simulate(event)}>
        <h3>Preparar campanha</h3>
        <label>Nome interno da campanha
          <input required minLength={3} maxLength={120} value={name}
            placeholder="Ex.: novidades de novembro" onChange={(e) => setName(e.target.value)} />
        </label>
        <label>Origem da base
          <select value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>
            {SOURCES.map((source) => <option key={source.value} value={source.value}>{source.title}</option>)}
          </select>
        </label>
        <label>Template aprovado pela Meta
          <select required value={templateKey} onChange={(e) => { setTemplateKey(e.target.value); setPreflight(null); }}>
            <option value="">Selecione um modelo aprovado</option>
            {approved.map((t) => <option key={`${t.name}::${t.language}`} value={`${t.name}::${t.language}`}>
              {t.name} · {t.language} · {t.category}
            </option>)}
          </select>
        </label>
        {selected ? <div className="waBulkPreview"><small>Prévia do template</small>
          <p>{selected.body || "Este modelo não disponibilizou prévia de texto."}</p>
          {selected.variables ? <small>{selected.variables} variável(is) exigem parametrização antes de qualquer envio real.</small> : null}
        </div> : <p className="waBulkHelp">Se não houver modelos aprovados, crie um na aba Modelos e aguarde aprovação da Meta.</p>}
        {audience && (provider === "capture" || provider === "all") ? <p className="waBulkHelp" role="status">
          Captação / Landing Pages: {fmt(audience.consent_claimed_count || 0)} aceite(s) WhatsApp declarado(s).
          Todos os cadastros com telefone desta origem recebem a campanha.
        </p> : null}
        {audience ? <p className="waBulkHelp">{audience.reason} {audience.truncated ? "Consulta incompleta." : ""}</p> : null}
        {preflight ? <p role="status" className={preflight.approved ? "waBulkSuccess" : "waBulkError"}>{preflight.note}</p> : null}
        {notice ? <p role="status" className="waBulkSuccess">{notice}</p> : null}
        {error ? <p role="alert" className="waBulkError">{error}</p> : null}
        <button type="submit" className="waBulkPrimary" disabled={loading || busy || !selected || !name.trim() || !audience || audience.truncated}>
          {busy ? "Verificando..." : "Salvar campanha"}
        </button>
        <p className="waBulkHelp">Salvar não envia nada. O envio começa só quando você clica em Enviar no histórico.
          Vai para todos os contatos com telefone da origem, sem repetir, menos quem respondeu SAIR, PARAR ou STOP.</p>
      </form>
      <section className="waBulkPanel" aria-label="Histórico de campanhas">
        <div className="waBulkHistoryHead"><h3>Histórico de campanhas</h3>
          <button type="button" onClick={() => void refresh()} disabled={busy || loading}>Atualizar</button></div>
        {draftsError ? <p className="waBulkError" role="alert">{draftsError}</p> : null}
        {loading ? <p>Carregando…</p> : drafts.length ? <div className="waBulkHistory">
          {drafts.map((d) => <article key={d.id}>
            <div><strong>{d.name}</strong><small>{d.template_name} · {d.language} · {new Date(d.created_at).toLocaleDateString("pt-BR")}</small>
              {d.status !== "draft" ? <small role="status">
                {fmt(d.sent_count || 0)} enviadas{d.recipients_count ? ` de ${fmt(d.recipients_count)}` : ""}
                {d.failed_count ? ` · ${fmt(d.failed_count)} falharam` : ""}{d.skipped_count ? ` · ${fmt(d.skipped_count)} pediram para sair` : ""}
              </small> : null}
              {d.last_error && d.status !== "sent" ? <small className="waBulkError">Último erro: {d.last_error}</small> : null}</div>
            <span className={`waBulkStatus is-${d.status}`}>{STATUS[d.status] || d.status}</span>
            {["draft", "partial", "failed"].includes(d.status) ? <button type="button" className="waBulkPrimary"
              disabled={Boolean(sendingId)} onClick={() => setConfirming(d)}>
              {sendingId === d.id ? "Começando…" : d.status === "draft" ? "Enviar" : "Retomar envio"}</button> : null}
          </article>)}
        </div> : <p className="waBulkEmpty">Nenhuma campanha planejada ainda.</p>}
      </section>
    </div>
    {confirming ? <div className="waBulkConfirm" role="dialog" aria-modal="true" aria-label="Confirmar envio">
      <div>
        <h3>Enviar "{confirming.name}"?</h3>
        <p>Vai para <b>todos os contatos com telefone</b> da origem {SOURCES.find((s) => s.value === (confirming.audience_provider || "all"))?.title || "escolhida"},
          {audience && provider === (confirming.audience_provider || "all") ? ` cerca de ${fmt(audience.sendable_count)} pessoas,` : ""} usando o modelo {confirming.template_name}.</p>
        <p className="waBulkWarn">Quem não aceitou receber WhatsApp da marca pode denunciar a mensagem. Muitas denúncias derrubam a
          qualidade do número e a Meta pode limitar ou bloquear o WhatsApp da marca. Não dá para desfazer depois de enviado.</p>
        <div className="waBulkConfirmActions">
          <button type="button" onClick={() => setConfirming(null)}>Cancelar</button>
          <button type="button" className="waBulkPrimary" onClick={() => void send(confirming)}>Enviar agora</button>
        </div>
      </div>
    </div> : null}
  </div>;
}
