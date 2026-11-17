import { useEffect, useState } from "react";
import {
  addRelationshipListMembers, createRelationshipList, deleteRelationshipList, listRelationshipLists,
  type RelationshipList,
} from "../../app/emailMarketing";

/** Listas compartilham a base da loja. Importar não concede consentimento. */
export default function RelationshipLists({ canEdit }: { canEdit: boolean }) {
  const [lists, setLists] = useState<RelationshipList[]>([]);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState("");
  const [emails, setEmails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function reload() {
    const result = await listRelationshipLists();
    setLists(result.lists);
  }
  useEffect(() => { let active = true; listRelationshipLists()
    .then((r) => { if (active) setLists(r.lists); })
    .catch(() => { if (active) setError("Não foi possível carregar as listas."); });
    return () => { active = false; }; }, []);
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
          setEmails(""); setNotice(`${result.accepted} contatos associados (sem enviar mensagens).`);
        })}>Adicionar à lista</button>
    </div> : null}
    {!lists.length && !error ? <p className="emMuted">Nenhuma lista cadastrada nesta empresa.</p> : null}
  </section>;
}
