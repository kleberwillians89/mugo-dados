import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  createWhatsAppCampaignDraft, listWhatsAppCampaignDrafts, listWhatsAppTemplates,
  preflightWhatsAppCampaignTemplate, previewWhatsAppCampaignAudience,
  type WaCampaignAudience, type WaCampaignDraft, type WaTemplate,
} from "../../app/whatsapp";
import "./WhatsAppBulkCampaigns.css";

type Provider = "all" | "shopify" | "fbits" | "whatsapp";
const SOURCES: { value: Provider; title: string }[] = [
  { value: "all", title: "Todas as origens" },
  { value: "shopify", title: "Shopify" },
  { value: "fbits", title: "Wake / FBITS" },
  { value: "whatsapp", title: "Conversas WhatsApp" },
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
    else setError((prev) => prev || "Não foi possível carregar os rascunhos.");
    setLoading(false);
  }, [tenant]);

  useEffect(() => {
    let active = true;
    setTemplates([]); setDrafts([]); setTemplateKey(""); setName(""); setPreflight(null);
    setError(""); setNotice(""); setLoading(true);
    Promise.allSettled([listWhatsAppTemplates(), listWhatsAppCampaignDrafts()]).then(([t, d]) => {
      if (!active || getActiveClientId() !== tenant) return;
      if (t.status === "fulfilled") setTemplates(t.value.templates);
      else setError("Modelos WhatsApp indisponíveis nesta empresa.");
      if (d.status === "fulfilled") setDrafts(d.value.drafts);
      else setError((old) => old || "Histórico de rascunhos indisponível.");
      setLoading(false);
    });
    return () => { active = false; };
  }, [tenant]);

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
