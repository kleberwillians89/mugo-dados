import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  listWhatsAppTemplates, submitWhatsAppTemplate,
  type WaTemplate, type WaTemplateInput,
} from "../../app/whatsapp";
import "./WhatsAppTemplates.css";

const initial = (): WaTemplateInput => ({
  name: "", category: "UTILITY", language: "pt_BR", body: "", footer: "", examples: [],
});
const vars = (body: string): number => Math.max(0, ...Array.from(body.matchAll(/\{\{(\d+)\}\}/g), (m) => Number(m[1])));
const PRESETS: Array<{ label: string; payload: WaTemplateInput }> = [
  { label: "Pedido confirmado", payload: {
    name: "pedido_confirmado", category: "UTILITY", language: "pt_BR",
    body: "Olá, {{1}}! Confirmamos seu pedido {{2}}. Se precisar de ajuda, estamos por aqui.",
    footer: "Atendimento da marca", examples: ["Ana", "12345"],
  } },
  { label: "Carrinho abandonado", payload: {
    name: "carrinho_abandonado", category: "MARKETING", language: "pt_BR",
    body: "Oi, {{1}}! Você deixou alguns itens no carrinho. Se ainda quiser finalizar, acesse: {{2}}. Responda SAIR para não receber ofertas.",
    footer: "Atendimento da marca", examples: ["Ana", "https://exemplo.com/carrinho"],
  } },
  { label: "First Access", payload: {
    name: "first_access_lancamento", category: "MARKETING", language: "pt_BR",
    body: "Oi, {{1}}! Seu acesso antecipado à nova coleção está liberado. Conheça as novidades em {{2}}. Responda SAIR para não receber novidades.",
    footer: "Atendimento da marca", examples: ["Ana", "https://exemplo.com/colecao"],
  } },
];
const statusLabel = (status: string) => ({
  APPROVED: "Aprovado", PENDING: "Em análise", REJECTED: "Rejeitado",
  PAUSED: "Pausado", DISABLED: "Desabilitado",
}[status] || status);
const purpose = (category: string) => category === "MARKETING" ? "Marketing" : "Utilidade";

export default function WhatsAppTemplates() {
  const clientId = getActiveClientId();
  const [templates, setTemplates] = useState<WaTemplate[]>([]);
  const [form, setForm] = useState<WaTemplateInput>(initial);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [available, setAvailable] = useState(true);
  const count = Math.min(5, vars(form.body));
  const update = (patch: Partial<WaTemplateInput>) => setForm((old) => ({ ...old, ...patch }));
  const refresh = useCallback(async () => {
    try {
      const result = await listWhatsAppTemplates();
      if (getActiveClientId() !== clientId) return;
      setTemplates(result.templates);
      setAvailable(true);
      setError("");
    } catch (cause) {
      if (getActiveClientId() !== clientId) return;
      const problem = cause instanceof Error ? cause.message : "Falha ao consultar modelos na Meta.";
      // CRM-owned numbers do not live in whatsapp_numbers. Never suggest
      // reconnecting an already connected CRM WhatsApp just to view templates.
      if (/número não encontrado|nenhum número cloud api/i.test(problem)) setAvailable(false);
      else { setAvailable(true); setError(problem); }
    } finally {
      if (getActiveClientId() === clientId) setLoading(false);
    }
  }, [clientId]);
  useEffect(() => { void refresh(); }, [refresh]);

  const preview = useMemo(() => form.body.replace(/\{\{(\d+)\}\}/g, (_, n: string) =>
    form.examples[Number(n) - 1]?.trim() || `{{${n}}}`), [form.body, form.examples]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !form.name.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      if (vars(form.body) > 5) throw new Error("Use até cinco variáveis consecutivas.");
      const result = await submitWhatsAppTemplate({
        ...form, examples: Array.from({ length: count }, (_, i) => form.examples[i] || ""),
      });
      setMessage(`Modelo "${result.template.name}" enviado à Meta. Status: ${statusLabel(result.template.status)}. Nenhuma mensagem foi disparada.`);
      setExpanded(false); setForm(initial());
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível enviar o modelo à Meta.");
    } finally { setBusy(false); }
  }

  return <section className="waCard waTemplateLibrary" aria-labelledby="wa-template-title">
    <div className="waCardHead waTemplateHead">
      <div>
        <h2 id="wa-template-title">Modelos de mensagens</h2>
        <p className="waMuted">Biblioteca da empresa selecionada. Crie mensagens e envie para aprovação da Meta antes de usar nas automações.</p>
      </div>
      <div className="waTemplateActions">
        <button className="waLinkButton" type="button" onClick={() => void refresh()} disabled={loading || busy}>Atualizar status</button>
        {available ? <button className="waPrimary" type="button" onClick={() => setExpanded((v) => !v)}>{expanded ? "Fechar" : "+ Criar modelo"}</button> : null}
      </div>
    </div>
    {!available ? <p className="waMuted" role="status">Esta empresa ainda não tem uma WABA disponível para gerenciar modelos. Se já usa MugôZap, confira o vínculo da organização com o CRM; não cadastre outro número.</p> : null}
    {message ? <p className="waTemplateSuccess" role="status">{message}</p> : null}
    {error ? <p className="waError" role="alert">{error}</p> : null}
    {loading ? <p className="waMuted">Consultando modelos…</p> : templates.length > 0
      ? <div className="waTemplateList">{templates.map((t) => <div className="waTemplateItem" key={t.name + t.language}>
        <div><strong>{t.name}</strong><small>{purpose(t.category)} · {t.language} · {t.variables} variáveis</small><p>{t.body}</p></div>
        <span className={t.status === "APPROVED" ? "waTemplateStatus is-approved" : "waTemplateStatus"}>{statusLabel(t.status)}</span>
      </div>)}</div>
      : available ? <p className="waMuted">Nenhum modelo encontrado nesta WABA.</p> : null}
    {expanded && available ? <form className="waTemplateForm" onSubmit={(e) => void submit(e)}>
      <div className="waTemplatePresets" role="group" aria-label="Exemplos editáveis de mensagens">
        {PRESETS.map((preset) => <button type="button" className="waLinkButton" key={preset.label}
          onClick={() => setForm({ ...preset.payload, examples: [...preset.payload.examples] })}>{preset.label}</button>)}
      </div>
      <div className="waTemplateGrid">
        <label>Nome interno do modelo
          <input required value={form.name} placeholder="ex: roove_carrinho_abandonado" maxLength={81}
            pattern="[a-z][a-z0-9_]{2,80}" onChange={(e) => update({ name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} />
        </label>
        <label>Categoria
          <select value={form.category} onChange={(e) => update({ category: e.target.value as WaTemplateInput["category"] })}>
            <option value="UTILITY">Utilidade — pedido e atendimento</option>
            <option value="MARKETING">Marketing — promoções e lançamentos</option>
          </select>
        </label>
        <label>Idioma
          <select value={form.language} onChange={(e) => update({ language: e.target.value as WaTemplateInput["language"] })}>
            <option value="pt_BR">Português (Brasil)</option><option value="en_US">Inglês</option><option value="es_ES">Espanhol</option>
          </select>
        </label>
      </div>
      <label>Texto da mensagem
        <textarea required rows={5} maxLength={1024} value={form.body}
          onChange={(e) => update({ body: e.target.value })}
          placeholder={"Olá, {{1}}! Seu pedido {{2}} foi confirmado. Acompanhe as novidades da marca."} />
      </label>
      <p className="waMuted">Para personalizar, use variáveis consecutivas: {"{{1}}"}, {"{{2}}"}… Preencha um exemplo de cada variável para revisão da Meta.</p>
      {count ? <div className="waTemplateGrid">{Array.from({ length: count }, (_, i) => <label key={i}>
        Exemplo de {"{{" + (i + 1) + "}}"}
        <input required value={form.examples[i] || ""} maxLength={100}
          placeholder={i === 0 ? "ex: Ana" : "ex: #12543"}
          onChange={(e) => setForm((old) => {
            const next = [...old.examples]; next[i] = e.target.value; return { ...old, examples: next };
          })} />
      </label>)}</div> : null}
      <label>Rodapé opcional
        <input maxLength={60} value={form.footer || ""} placeholder="Ex.: Equipe Roove"
          onChange={(e) => update({ footer: e.target.value })} />
      </label>
      <div className="waTemplatePreview">
        <strong>Prévia da mensagem</strong>
        <p>{preview || "Seu texto aparecerá aqui."}</p>
        {form.footer ? <small>{form.footer}</small> : null}
      </div>
      <p className="waMuted">Enviar à Meta solicita aprovação deste modelo; não envia mensagens aos clientes. O modelo só poderá ser usado em automações após aprovação e consentimento dos destinatários.</p>
      <div className="waFormActions">
        <button className="waPrimary" type="submit" disabled={busy || !form.name || !form.body}>
          {busy ? "Enviando à Meta…" : "Enviar modelo para aprovação"}
        </button>
        <button type="button" className="waLinkButton" onClick={() => setExpanded(false)} disabled={busy}>Cancelar</button>
      </div>
    </form> : null}
  </section>;
}
