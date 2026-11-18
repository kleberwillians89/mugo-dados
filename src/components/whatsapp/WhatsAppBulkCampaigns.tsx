import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  createWhatsAppCampaignDraft, listWhatsAppCampaignDrafts, listWhatsAppTemplates,
  getWhatsAppContactImportStatus, importExistingCommerceContacts, importExistingWhatsAppConversations,
  preflightWhatsAppCampaignTemplate, previewWhatsAppCampaignAudience,
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
        ? "Template aprovado. Simulação concluída; nenhuma mensagem foi enviada."
        : "O template não está aprovado na Meta. Selecione outro modelo." });
      if (!t.template_approved) return;
      const response = await createWhatsAppCampaignDraft({
        name: name.trim(), template_name: selected.name, language: selected.language, provider,
      });
      if (getActiveClientId() !== tenant) return;
      setNotice(`Rascunho salvo com sucesso. Mensagens enviadas: ${response.messages_sent}.`);
      await refresh();
    } catch (cause) {
      if (getActiveClientId() === tenant) setError(cause instanceof Error ? cause.message : "Não foi possível simular a campanha.");
    } finally { setBusy(false); }
  }

  return <div className="waBulk">
    <header className="waBulkHeading">
      <div>
        <h2>Disparos em massa</h2>
        <p>Planeje campanhas para a empresa selecionada. Primeira etapa: prévia e simulação segura.</p>
      </div>
      <span className="waBulkChip">Envio real bloqueado</span>
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
      <div><small>Elegíveis para envio agora</small><strong>0</strong></div>
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
          Os cadastros ficam visíveis nesta origem, mas não entram automaticamente na fila de envio.
        </p> : null}
        {audience ? <p className="waBulkHelp">{audience.reason} {audience.truncated ? "Consulta incompleta." : ""}</p> : null}
        {preflight ? <p role="status" className={preflight.approved ? "waBulkSuccess" : "waBulkError"}>{preflight.note}</p> : null}
        {notice ? <p role="status" className="waBulkSuccess">{notice}</p> : null}
        {error ? <p role="alert" className="waBulkError">{error}</p> : null}
        <button type="submit" className="waBulkPrimary" disabled={loading || busy || !selected || !name.trim() || !audience || audience.truncated}>
          {busy ? "Verificando..." : "Simular e salvar rascunho"}
        </button>
        <p className="waBulkHelp">Nenhum destinatário será contatado. O envio real só será disponibilizado após validação de telefone, opt-in, descadastro e fila segura.</p>
      </form>
      <section className="waBulkPanel" aria-label="Histórico de campanhas">
        <div className="waBulkHistoryHead"><h3>Histórico de campanhas</h3>
          <button type="button" onClick={() => void refresh()} disabled={busy || loading}>Atualizar</button></div>
        {draftsError ? <p className="waBulkError" role="alert">{draftsError}</p> : null}
        {loading ? <p>Carregando…</p> : drafts.length ? <div className="waBulkHistory">
          {drafts.map((d) => <article key={d.id}>
            <div><strong>{d.name}</strong><small>{d.template_name} · {d.language}</small></div>
            <span>Rascunho</span>
            <small>{new Date(d.created_at).toLocaleDateString("pt-BR")}</small>
          </article>)}
        </div> : <p className="waBulkEmpty">Nenhuma campanha planejada ainda.</p>}
      </section>
    </div>
  </div>;
}
