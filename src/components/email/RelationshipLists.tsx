import { useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  addRelationshipListMembers, contactEmailHistory, createRelationshipList, deleteRelationshipList, listRelationshipLists, removeRelationshipListMembers,
  previewAudience, type AudiencePreview, type RelationshipList, type ContactEmailEvent,
} from "../../app/emailMarketing";

/** Listas compartilham a base da loja. Importar não concede consentimento. */
export default function RelationshipLists({ canEdit }: { canEdit: boolean }) {
  const tenant = getActiveClientId();
  const [lists, setLists] = useState<RelationshipList[]>([]);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState("");
  const [emails, setEmails] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyEmail, setHistoryEmail] = useState("");
  const [events, setEvents] = useState<ContactEmailEvent[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [audience, setAudience] = useState<AudiencePreview | null>(null);
  const [audienceLoading, setAudienceLoading] = useState(false);
  const [audienceError, setAudienceError] = useState("");
  async function reload() {
    const result = await listRelationshipLists();
    if (getActiveClientId() === tenant) setLists(result.lists);
  }
  useEffect(() => { let active = true;
    setLists([]); setSelected(""); setEmails(""); setEvents(null); setError(""); setNotice("");
    listRelationshipLists()
    .then((r) => { if (active && getActiveClientId() === tenant) setLists(r.lists); })
    .catch(() => { if (active && getActiveClientId() === tenant) setError("Não foi possível carregar as listas."); });
    return () => { active = false; }; }, [tenant]);
  async function refreshEmailAudience() {
    setAudienceLoading(true); setAudienceError("");
    const currentTenant = tenant;
    try {
      const result = await previewAudience({ segment: "consentimento", days: 90, only_consent: true });
      if (getActiveClientId() === currentTenant) setAudience(result);
    } catch (cause) {
      if (getActiveClientId() === currentTenant)
        setAudienceError(cause instanceof Error ? cause.message : "Não foi possível consultar a Shopify.");
    } finally {
      if (getActiveClientId() === currentTenant) setAudienceLoading(false);
    }
  }
  useEffect(() => {
    let active = true;
    setAudience(null); setAudienceError(""); setAudienceLoading(true);
    previewAudience({ segment: "consentimento", days: 90, only_consent: true })
      .then((result) => { if (active && getActiveClientId() === tenant) setAudience(result); })
      .catch((cause) => { if (active && getActiveClientId() === tenant)
        setAudienceError(cause instanceof Error ? cause.message : "Não foi possível consultar a base de e-mails."); })
      .finally(() => { if (active && getActiveClientId() === tenant) setAudienceLoading(false); });
    return () => { active = false; };
  }, [tenant]);
  async function action(task: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await task(); await reload(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Operação não concluída."); }
    finally { setBusy(false); }
  }
  return <section className="emCard">
    <header className="emCardHead"><div>
      <h2>Listas de Relacionamento</h2>
      <p className="emMuted">Organize públicos por empresa. E-mails importados são convertidos em identificadores;
        só recebem campanhas os contatos já presentes na origem com consentimento verificável e sem descadastro.</p>
    </div></header>
    <div className="emCard" aria-label="Contatos de e-mail da empresa">
      <h3>Base de e-mail da loja conectada</h3>
      <p className="emMuted">A plataforma já lê os cadastros existentes da Shopify ou Wake/FBITS.
        Não é necessário importar os mesmos e-mails novamente.
        Campanhas só incluem endereços com opt-in confirmado na origem e sem descadastro.</p>
      {audience ? <div className="emInlineRow" role="status">
        <strong>Cadastros: {audience.base.toLocaleString("pt-BR")}</strong>
        <strong>Com aceite: {audience.with_consent.toLocaleString("pt-BR")}</strong>
        <strong>Disponíveis para campanha: {audience.count.toLocaleString("pt-BR")}</strong>
        <span className="emMuted">Fonte: {audience.provider || "não conectada"}</span>
      </div> : null}
      {audience && !audience.consent_known ? <p className="emMuted">
        A fonte não confirma opt-in de e-mail; contatos sem comprovação ficam fora das campanhas.</p> : null}
      {audienceError ? <p className="emError" role="alert">{audienceError}</p> : null}
      <button type="button" className="ds-button" disabled={audienceLoading}
        onClick={() => void refreshEmailAudience()}>
        {audienceLoading ? "Consultando base..." : "Atualizar contagem da base"}
      </button>
    </div>
    {error ? <p className="emError" role="alert">{error}</p> : null}
    {notice ? <p className="emOk" role="status">{notice}</p> : null}
    {canEdit ? <div className="emInlineRow">
      <input aria-label="Nome da lista" placeholder="Ex.: Clientes VIP" value={name}
        maxLength={100} disabled={busy} onChange={(e) => setName(e.target.value)} />
      <button type="button" className="ds-button is-primary" disabled={busy || !name.trim()}
        onClick={() => void action(async () => {
          const result = await createRelationshipList(name.trim());
          setSelected(result.list.id); setName("");
          setNotice("Lista criada.");
        })}>Criar lista</button>
    </div> : null}
    <div className="emInlineRow">
      <select aria-label="Lista selecionada" value={selected} disabled={busy || !lists.length}
        onChange={(e) => setSelected(e.target.value)}>
        <option value="">Selecionar lista</option>
        {lists.map((list) => <option key={list.id} value={list.id}>{list.name}</option>)}
      </select>
      {canEdit && selected ? <button type="button" className="ds-button is-danger" disabled={busy}
        onClick={() => { if (window.confirm("Excluir esta lista? Campanhas que a utilizam precisarão selecionar outro público."))
          void action(async () => { await deleteRelationshipList(selected); setSelected(""); setNotice("Lista excluída."); }); }}>
        Excluir lista</button> : null}
    </div>
    {canEdit && selected ? <div className="emCard">
      <h3>Adicionar contatos</h3>
      <p className="emMuted">Cole até 500 e-mails separados por linha, vírgula ou ponto e vírgula. Não cria opt-in nem
        autoriza disparos. Apenas quem já aceitou marketing na plataforma conectada poderá receber.</p>
      <textarea aria-label="E-mails para adicionar" value={emails} rows={5} disabled={busy}
        onChange={(e) => setEmails(e.target.value)} placeholder={"ana@exemplo.com\nbeatriz@exemplo.com"} />
      <button type="button" className="ds-button is-primary" disabled={busy || !emails.trim()}
        onClick={() => void action(async () => {
          const entries = emails.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
          const result = await addRelationshipListMembers(selected, entries);
          setEmails(""); setNotice(`${result.accepted} elegíveis associados; ${result.not_eligible} ignorados sem opt-in verificável ou fora da base; ${result.duplicates_in_input} duplicados.`);
        })}>Adicionar à lista</button>
      <button type="button" className="ds-button" disabled={busy || !emails.trim()}
        onClick={() => { if (window.confirm("Remover estes contatos da lista selecionada?"))
          void action(async () => {
            const entries = emails.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
            const result = await removeRelationshipListMembers(selected, entries);
            setEmails(""); setNotice(`${result.processed} identificadores processados para remoção.`);
          }); }}>Remover da lista</button>
    </div> : null}
    {canEdit ? <div className="emCard">
      <h3>Histórico de e-mails do contato</h3>
      <p className="emMuted">Consulta restrita à empresa atual. O endereço não é armazenado neste histórico;
        retornam somente eventos técnicos de envio, entrega, abertura e falha.</p>
      <div className="emInlineRow">
        <input type="email" aria-label="Pesquisar e-mail no histórico" placeholder="cliente@exemplo.com"
          value={historyEmail} disabled={busy} onChange={(e) => { setHistoryEmail(e.target.value); setEvents(null); }} />
        <button type="button" className="ds-button" disabled={busy || !historyEmail.trim()}
          onClick={() => void action(async () => {
            setEvents((await contactEmailHistory(historyEmail)).entries);
          })}>Consultar histórico</button>
      </div>
      {events ? <div aria-live="polite">{events.length ? <table className="emTable">
        <thead><tr><th>Data</th><th>Tipo</th><th>Status</th></tr></thead>
        <tbody>{events.map((event, index) => <tr key={index}>
          <td>{new Date(event.created_at).toLocaleDateString("pt-BR")}</td>
          <td>{event.kind}</td><td>{event.status}</td>
        </tr>)}</tbody>
      </table> : <p className="emMuted">Nenhum envio registrado para este contato nesta empresa.</p>}</div> : null}
    </div> : null}
    {!lists.length && !error ? <p className="emMuted">Nenhuma lista cadastrada nesta empresa.</p> : null}
  </section>;
}
