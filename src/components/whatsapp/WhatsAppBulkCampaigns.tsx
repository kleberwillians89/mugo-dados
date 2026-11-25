import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  createWhatsAppCampaignDraft, listWhatsAppCampaignDrafts, listWhatsAppTemplates,
  getWhatsAppContactImportStatus, importExistingCommerceContacts, importExistingWhatsAppConversations, importContactsSheet,
  preflightWhatsAppCampaignTemplate, previewWhatsAppCampaignAudience, sendWhatsAppCampaign, cancelWhatsAppCampaign, testWhatsAppCampaign,
  getWhatsAppCampaignReport, type WaCampaignReport,
  type WaCampaignAudience, type WaCampaignDraft, type WaTemplate, type WaContactImportStatus,
} from "../../app/whatsapp";
import { uploadArt } from "../../app/artUpload";
import SheetRecipientsPicker from "./SheetRecipientsPicker";
import "./WhatsAppBulkCampaigns.css";

type Provider = "all" | "shopify" | "fbits" | "whatsapp" | "capture" | "planilha";
const SOURCES: { value: Provider; title: string }[] = [
  { value: "all", title: "Todas as origens" },
  { value: "shopify", title: "Shopify" },
  { value: "fbits", title: "Wake / FBITS" },
  { value: "whatsapp", title: "Conversas WhatsApp" },
  { value: "capture", title: "Captação / Landing Pages" },
  { value: "planilha", title: "Planilha importada (Excel/CSV)" },
];
const fmt = (n: number) => new Intl.NumberFormat("pt-BR").format(n);
const STATUS: Record<WaCampaignDraft["status"], string> = {
  draft: "Pronta para enviar", queued: "Na fila", sending: "Enviando…", sent: "Enviada", partial: "Enviada em parte", failed: "Falhou",
};
const MEDIA_HEADERS = new Set(["IMAGE", "VIDEO", "DOCUMENT"]);
const stamp = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
function statusLabel(d: WaCampaignDraft) {
  if (d.status === "queued") return d.scheduled_at && new Date(d.scheduled_at) > new Date() ? `Agendada · ${stamp(d.scheduled_at)}` : "Na fila · começa em até 5 min";
  return STATUS[d.status] || d.status;
}

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
  const [sheet, setSheet] = useState<File | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);  // null = todos da planilha
  const [sheetConsent, setSheetConsent] = useState(false);
  const [sheetReplace, setSheetReplace] = useState(false);
  const [sheetBusy, setSheetBusy] = useState(false);
  const [draftsError, setDraftsError] = useState("");
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<WaCampaignDraft | null>(null);
  const [when, setWhen] = useState<"now" | "later">("now");
  const [scheduleAt, setScheduleAt] = useState("");
  const [excludePrevious, setExcludePrevious] = useState(true);
  const [headerUrl, setHeaderUrl] = useState("");
  const [headerBusy, setHeaderBusy] = useState(false);
  const [testPhone, setTestPhone] = useState("");
  const [testName, setTestName] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [reports, setReports] = useState<Record<string, WaCampaignReport | "loading" | string>>({});

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
    setTestPhone(""); setTestName(""); setTestResult(null); setTesting(false);
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

  const anySending = drafts.some((d) => d.status === "sending" || d.status === "queued");
  useEffect(() => {
    if (!anySending) return;
    const timer = window.setInterval(() => {
      listWhatsAppCampaignDrafts().then((r) => { if (getActiveClientId() === tenant) setDrafts(r.drafts); }).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [anySending, tenant]);

  async function send(draft: WaCampaignDraft) {
    if (when === "later" && !scheduleAt) { setError("Escolha a data e a hora do envio."); return; }
    setConfirming(null); setExcludePrevious(true); setSendingId(draft.id); setError(""); setNotice("");
    try {
      const r = await sendWhatsAppCampaign(draft.id, when === "later" ? new Date(scheduleAt).toISOString() : null, excludePrevious);
      if (getActiveClientId() !== tenant) return;
      setNotice(r.scheduled_at
        ? `Agendada para ${stamp(r.scheduled_at)} (até ${fmt(r.recipients_count)} contatos). Dá para cancelar até lá.`
        : `Na fila para até ${fmt(r.recipients_count)} contatos: o envio começa em até 5 minutos e segue mesmo com a tela fechada.`);
      await refresh();
    } catch (cause) {
      if (getActiveClientId() === tenant) setError(cause instanceof Error ? cause.message : "Não foi possível começar o envio.");
    } finally { setSendingId(null); }
  }

  async function sendTest() {
    if (!selected || testing || !testPhone.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testWhatsAppCampaign({
        phone: testPhone.trim(), template_name: selected.name, language: selected.language,
        header_media_url: headerUrl || undefined, recipient_name: testName.trim() || undefined,
      });
      if (getActiveClientId() === tenant) {
        setTestResult({ ok: true, message: result.recorded === false
          ? "A Meta aceitou o teste, mas ele não foi salvo em Conversas. Confira a entrega no WhatsApp."
          : "A Meta aceitou o teste. Veja o registro em Conversas → Campanhas e confira a entrega no WhatsApp." });
      }
    } catch (cause) {
      if (getActiveClientId() === tenant) {
        setTestResult({ ok: false, message: cause instanceof Error ? cause.message : "Não foi possível enviar o teste." });
      }
    } finally {
      if (getActiveClientId() === tenant) setTesting(false);
    }
  }

  async function cancelDraft(draft: WaCampaignDraft) {
    setSendingId(draft.id); setError("");
    try { await cancelWhatsAppCampaign(draft.id); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível cancelar."); }
    finally { setSendingId(null); }
  }

  async function loadReport(draft: WaCampaignDraft) {
    setReports((r) => ({ ...r, [draft.id]: "loading" }));
    try {
      const rep = await getWhatsAppCampaignReport(draft.id);
      setReports((r) => ({ ...r, [draft.id]: rep }));
    } catch (cause) {
      setReports((r) => ({ ...r, [draft.id]: cause instanceof Error ? cause.message : "Relatório indisponível agora." }));
    }
  }

  async function uploadHeader(file: File | undefined) {
    if (!file) return;
    setHeaderBusy(true); setError("");
    try { setHeaderUrl(await uploadArt(null, file)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível enviar o arquivo."); }
    finally { setHeaderBusy(false); }
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

  async function importSheet(event: FormEvent) {
    event.preventDefault();
    if (!sheet || !sheetConsent || sheetBusy) return;
    setSheetBusy(true); setImportError(""); setImportNote("");
    const selectedTenant = tenant;
    try {
      const r = await importContactsSheet(sheet, { replace: sheetReplace, consent: sheetConsent });
      if (getActiveClientId() !== selectedTenant) return;
      setImportNote(`${fmt(r.contacts_imported)} contato(s) importado(s) da planilha (coluna "${r.columns.telefone}"`
        + `${r.columns.nome ? `, nomes de "${r.columns.nome}"` : ""})${r.invalid ? `; ${fmt(r.invalid)} linha(s) sem telefone válido ficaram de fora` : ""}.`
        + " Escolha \"Planilha importada\" na origem para disparar para eles.");
      setSheet(null); setProvider("planilha");
      const [status, currentAudience] = await Promise.all([getWhatsAppContactImportStatus(), previewWhatsAppCampaignAudience("planilha")]);
      if (getActiveClientId() !== selectedTenant) return;
      setImportStatus(status); setAudience(currentAudience);
    } catch (cause) {
      if (getActiveClientId() === selectedTenant) setImportError(cause instanceof Error ? cause.message : "Não consegui importar a planilha.");
    } finally { setSheetBusy(false); }
  }

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
        ...(provider === "planilha" && picked ? { selected_contacts: picked } : {}),
        ...(selected.header && MEDIA_HEADERS.has(selected.header) && headerUrl ? { header_media_url: headerUrl } : {}),
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
        <p className="waBulkHelp">Traga a base da loja, as conversas do WhatsApp ou uma planilha de leads. Importar não envia nenhuma mensagem.</p>
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
        {" · "}Planilha: {fmt(importStatus.by_provider.planilha || 0)}
        {importStatus.truncated ? " · Contagem parcial" : ""}
      </p> : null}
      <form className="waBulkSheet" onSubmit={(e) => void importSheet(e)} aria-label="Importar leads de planilha">
        <label className="waBulkSheetFile">
          <span>Leads de planilha (Excel .xlsx ou .csv)</span>
          <input type="file" accept=".xlsx,.xlsm,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => setSheet(e.target.files?.[0] || null)} disabled={sheetBusy} />
          <small>Precisa de uma coluna de telefone (Telefone, Celular ou WhatsApp) com DDD. Nome e e-mail são opcionais. Até 20 mil linhas.</small>
        </label>
        <label className="waBulkCheck"><input type="checkbox" checked={sheetConsent} onChange={(e) => setSheetConsent(e.target.checked)} />
          Confirmo que esses contatos aceitaram receber mensagens da marca.</label>
        <label className="waBulkCheck"><input type="checkbox" checked={sheetReplace} onChange={(e) => setSheetReplace(e.target.checked)} />
          Substituir a planilha importada antes (senão, soma aos leads já importados).</label>
        <button type="submit" disabled={!sheet || !sheetConsent || sheetBusy}>{sheetBusy ? "Importando planilha..." : "Importar planilha"}</button>
      </form>
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
          <select value={provider} onChange={(e) => { setProvider(e.target.value as Provider); setPicked(null); }}>
            {SOURCES.map((source) => <option key={source.value} value={source.value}>{source.title}</option>)}
          </select>
        </label>
        {provider === "planilha" ? <SheetRecipientsPicker picked={picked} onChange={setPicked} /> : null}
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
        {selected?.header && MEDIA_HEADERS.has(selected.header) ? <label>{selected.header === "IMAGE" ? "Imagem do topo" : selected.header === "VIDEO" ? "Vídeo do topo" : "Arquivo do topo"} (o modelo pede)
          <input type="file" accept={selected.header === "IMAGE" ? "image/png,image/jpeg" : selected.header === "VIDEO" ? "video/mp4" : "application/pdf"}
            disabled={headerBusy} onChange={(e) => void uploadHeader(e.currentTarget.files?.[0])} />
          {headerBusy ? <small>Enviando…</small> : headerUrl ? (selected.header === "IMAGE" ? <img className="waBulkHeaderPreview" src={headerUrl} alt="" /> : <small>Arquivo pronto.</small>) : null}
        </label> : null}
        {selected ? <fieldset>
          <legend>Enviar teste pelo WhatsApp</legend>
          <label>Número com DDD
            <input type="tel" autoComplete="off" maxLength={32} value={testPhone} placeholder="(11) 99999-9999"
              disabled={testing} onChange={(e) => { setTestPhone(e.target.value); setTestResult(null); }} />
          </label>
          {selected.variables === 1 ? <label>Primeiro nome para o teste
            <input value={testName} maxLength={100} disabled={testing}
              onChange={(e) => { setTestName(e.target.value); setTestResult(null); }} />
          </label> : null}
          <button type="button" onClick={() => void sendTest()} disabled={testing || !testPhone.trim() || (selected.variables === 1 && !testName.trim()) || headerBusy
            || Boolean(selected.header && MEDIA_HEADERS.has(selected.header) && !headerUrl)}>
            {testing ? "Enviando teste…" : "Enviar teste"}
          </button>
          {testResult ? <p role={testResult.ok ? "status" : "alert"}
            className={testResult.ok ? "waBulkSuccess" : "waBulkError"}>{testResult.message}</p> : null}
        </fieldset> : null}
        {audience && (provider === "capture" || provider === "all") ? <p className="waBulkHelp" role="status">
          Captação / Landing Pages: {fmt(audience.consent_claimed_count || 0)} aceite(s) WhatsApp declarado(s).
          Esta contagem não confirma destinatários aptos. Confira a prévia antes de enviar.
        </p> : null}
        {audience ? <p className="waBulkHelp">{audience.reason} {audience.truncated ? "Consulta incompleta." : ""}</p> : null}
        {preflight ? <p role="status" className={preflight.approved ? "waBulkSuccess" : "waBulkError"}>{preflight.note}</p> : null}
        {notice ? <p role="status" className="waBulkSuccess">{notice}</p> : null}
        {error ? <p role="alert" className="waBulkError">{error}</p> : null}
        <button type="submit" className="waBulkPrimary" disabled={loading || busy || !selected || !name.trim() || !audience || audience.truncated
          || Boolean(selected?.header && MEDIA_HEADERS.has(selected.header) && !headerUrl)
          || (provider === "planilha" && picked !== null && !picked.length)}>
          {busy ? "Verificando..." : provider === "planilha" && picked?.length ? `Salvar campanha para ${picked.length} contato(s)` : "Salvar campanha"}
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
              <small>Base: {SOURCES.find((source) => source.value === d.audience_provider)?.title ?? "Origem não registrada"}</small>
              {d.status !== "draft" ? <small role="status">
                {fmt(d.sent_count || 0)} enviadas{d.recipients_count ? ` de ${fmt(d.recipients_count)}` : ""}
                {d.failed_count ? ` · ${fmt(d.failed_count)} falharam` : ""}{d.skipped_count ? ` · ${fmt(d.skipped_count)} foram puladas` : ""}
              </small> : null}
              {d.last_error && d.status !== "sent" ? <small className="waBulkError">Último erro: {d.last_error}</small> : null}</div>
            <span className={`waBulkStatus is-${d.status}`}>{statusLabel(d)}</span>
            {["draft", "partial", "failed"].includes(d.status) ? <button type="button" className="waBulkPrimary"
              disabled={Boolean(sendingId)} onClick={() => { setWhen("now"); setScheduleAt(""); setConfirming(d); }}>
              {sendingId === d.id ? "Começando…" : d.status === "draft" ? "Enviar ou agendar" : "Retomar envio"}</button> : null}
            {d.status === "queued" ? <button type="button" disabled={Boolean(sendingId)} onClick={() => void cancelDraft(d)}>Cancelar</button> : null}
            {["sent", "partial"].includes(d.status) ? <button type="button" onClick={() => void loadReport(d)}
              disabled={reports[d.id] === "loading"}>{reports[d.id] === "loading" ? "Calculando…" : "Ver resultado"}</button> : null}
            {typeof reports[d.id] === "object" ? (() => { const r = reports[d.id] as WaCampaignReport; return <div className="waBulkReport" role="status">
              <span><b>{fmt(r.sent)}</b> enviadas</span>
              <span><b>{fmt(r.replied)}</b> responderam ({r.reply_rate.toLocaleString("pt-BR")}%)</span>
              {r.sales_available ? <span><b>{fmt(r.buyers)}</b> compraram em 7 dias · {brl(r.revenue)}</span> : <span>Vendas: loja não conectada</span>}
              <small>{r.window} · cruzado pelo telefone</small>
            </div>; })() : typeof reports[d.id] === "string" && reports[d.id] !== "loading" ? <small className="waBulkError">{reports[d.id] as string}</small> : null}
          </article>)}
        </div> : <p className="waBulkEmpty">Nenhuma campanha planejada ainda.</p>}
      </section>
    </div>
    {confirming ? <div className="waBulkConfirm" role="dialog" aria-modal="true" aria-label="Confirmar envio">
      <div>
        <h3>Enviar "{confirming.name}"?</h3>
        <p>O modelo {confirming.template_name} será enviado aos contatos selecionados, uma vez por número.</p>
        <label>
          <input type="checkbox" checked={excludePrevious} onChange={(e) => setExcludePrevious(e.target.checked)} />
          Pular números que já receberam este modelo em outra campanha
        </label>
        <div className="waBulkWhen" role="radiogroup" aria-label="Quando enviar">
          <label><input type="radio" checked={when === "now"} onChange={() => setWhen("now")} /> Enviar agora (começa em até 5 min)</label>
          <label><input type="radio" checked={when === "later"} onChange={() => setWhen("later")} /> Agendar</label>
          {when === "later" ? <input type="datetime-local" aria-label="Data e hora do envio" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)} /> : null}
        </div>
        <p className="waBulkWarn">Quem não aceitou receber WhatsApp da marca pode denunciar a mensagem. Muitas denúncias derrubam a
          qualidade do número e a Meta pode limitar ou bloquear o WhatsApp da marca. Não dá para desfazer depois de enviado.</p>
        <div className="waBulkConfirmActions">
          <button type="button" onClick={() => { setConfirming(null); setExcludePrevious(true); }}>Cancelar</button>
          <button type="button" className="waBulkPrimary" onClick={() => void send(confirming)}>{when === "later" ? "Agendar envio" : "Enviar agora"}</button>
        </div>
      </div>
    </div> : null}
  </div>;
}
