import { useState } from "react";
import { ArrowRight, Check, FileText, Mail, Megaphone } from "lucide-react";
import { createFromMugoIA, type MugoIAAction as Action } from "../../app/studio";
import { navigateToAppRoute } from "../../app/routes";

const KIND = {
  email: { icon: Mail, label: "E-mail marketing", button: "Criar no E-mail Marketing" },
  campanha_meta: { icon: Megaphone, label: "Campanha na Meta", button: "Criar rascunho na Mídia On" },
  briefing: { icon: FileText, label: "Briefing", button: "Criar briefing" },
} as const;
const money = (n?: number) => (n ? n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "a definir");

/** Proposta da Mugô IA → rascunho na ferramenta. Nada é enviado nem publicado daqui. */
export default function MugoIAAction({ messageId, action, canCreate, onChange }: {
  messageId: string | null; action: Action; canCreate: boolean; onChange: (action: Action) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kind = KIND[action.tipo];
  if (!kind) return null;
  const Icon = kind.icon;

  async function create() {
    if (!messageId) return;
    setBusy(true); setError(null);
    try { onChange((await createFromMugoIA(messageId)).acao); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não consegui criar agora. Tente de novo."); }
    finally { setBusy(false); }
  }

  return <section className="miaAction" data-testid="mia-action" data-kind={action.tipo}>
    <header><Icon size={16} aria-hidden="true" /><small>{kind.label}</small><b>{action.titulo}</b></header>
    {action.tipo === "email" ? <dl>
      <div><dt>Assunto</dt><dd>{action.assunto}</dd></div>
      {action.preheader ? <div><dt>Pré-header</dt><dd>{action.preheader}</dd></div> : null}
    </dl> : null}
    {action.tipo === "campanha_meta" ? <dl>
      <div><dt>Objetivo</dt><dd>{action.objetivo || "vendas"}</dd></div>
      <div><dt>Verba</dt><dd>{money(action.verba_diaria)}/dia · {action.dias || 14} dias</dd></div>
    </dl> : null}
    {action.status === "criado" && action.criado ? <p className="miaActionDone">
      <Check size={15} aria-hidden="true" /> Rascunho criado em {action.criado.label}{action.criado.name ? `: ${action.criado.name}` : ""}.
      <button type="button" className="miaGhost" onClick={() => navigateToAppRoute(action.criado!.route)}>Abrir <ArrowRight size={14} aria-hidden="true" /></button>
    </p> : canCreate ? <div className="miaActionRow">
      <button type="button" className="ds-button ds-button--primary" disabled={busy || !messageId} onClick={() => void create()}>
        {busy ? "Criando o rascunho…" : kind.button}</button>
      <small>Vira rascunho para revisar. Nada é enviado nem publicado sem vocês.</small>
    </div> : <small className="miaHint">Quem administra a marca pode criar este rascunho.</small>}
    {error ? <p role="alert" className="studioError">{error}</p> : null}
  </section>;
}
