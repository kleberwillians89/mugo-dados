import { useState } from "react";
import { ArrowRight, Check, FileText, Mail, Megaphone, MessageCircle } from "lucide-react";
import { createFromMugoIA, type MugoIAAction as Action } from "../../app/studio";
import { openCreated } from "./openCreated";

const KIND = {
  email: { icon: Mail, label: "E-mail marketing", button: "Criar no E-mail Marketing" },
  campanha_meta: { icon: Megaphone, label: "Campanha na Meta", button: "Criar rascunho na Mídia On" },
  briefing: { icon: FileText, label: "Briefing", button: "Criar briefing" },
  whatsapp_modelo: { icon: MessageCircle, label: "Mensagem de WhatsApp", button: "Enviar para aprovação da Meta" },
} as const;

const money = (n?: number) => (n ? n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "a definir");

/** Proposta da Mugô IA → rascunho na ferramenta. Nada é enviado nem publicado daqui. */
export default function MugoIAAction({ messageId, action, canCreate, onChange, item = 0 }: {
  messageId: string | null; action: Action; canCreate: boolean; onChange: (action: Action) => void; item?: number;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [buttonText, setButtonText] = useState(action.wa_botao_texto || "Entrar no grupo");
  const [buttonUrl, setButtonUrl] = useState(action.wa_botao_url || "");
  const kind = KIND[action.tipo];
  if (!kind) return null;
  const Icon = kind.icon;

  async function create() {
    if (!messageId) return;
    setBusy(true); setError(null);
    const url = buttonUrl.trim();
    if (action.tipo === "whatsapp_modelo" && url && !/^https:\/\/\S{4,}$/.test(url)) { setError("O link do botão precisa começar com https://."); setBusy(false); return; }
    const edits = action.tipo === "whatsapp_modelo" ? { wa_botao_url: url, wa_botao_texto: buttonText.trim().slice(0, 25) } : undefined;
    try { onChange((await createFromMugoIA(messageId, item, edits)).acao); }
    catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não consegui criar agora. Tente de novo."); }
    finally { setBusy(false); }
  }

  return <section className="miaCreate" data-testid="mia-action" data-kind={action.tipo}>
    <header><Icon size={16} aria-hidden="true" /><small>{kind.label}</small><b>{action.titulo}</b></header>
    {action.tipo === "email" ? <dl>
      <div><dt>Assunto</dt><dd>{action.assunto}</dd></div>
      {action.preheader ? <div><dt>Pré-header</dt><dd>{action.preheader}</dd></div> : null}
    </dl> : null}
    {action.tipo === "campanha_meta" ? <dl>
      <div><dt>Objetivo</dt><dd>{action.objetivo || "vendas"}</dd></div>
      <div><dt>Verba</dt><dd>{money(action.verba_diaria)}/dia · {action.dias || 14} dias</dd></div>
    </dl> : null}
    {action.tipo === "whatsapp_modelo" ? <blockquote className="miaCreateWa">{action.wa_corpo}{action.wa_rodape ? <small>{action.wa_rodape}</small> : null}</blockquote> : null}
    {action.tipo === "whatsapp_modelo" && action.status !== "criado" && canCreate ? <div className="miaCreateButton">
      <label>Botão<input value={buttonText} maxLength={25} onChange={(e) => setButtonText(e.target.value)} /></label>
      <label>Link do botão (grupo ou página)<input value={buttonUrl} placeholder="https://chat.whatsapp.com/…" inputMode="url"
        onChange={(e) => setButtonUrl(e.target.value)} /></label>
      {!buttonUrl.trim() ? <small>Sem link, o modelo vai sem botão.</small> : null}
    </div> : null}
    {action.tipo === "whatsapp_modelo" && action.status === "criado" && action.wa_botao_url ? <small className="miaHint">Botão: {action.wa_botao_texto} → {action.wa_botao_url}</small> : null}
    {action.status === "criado" && action.criado ? <><p className="miaCreateDone">
      <Check size={15} aria-hidden="true" /> {action.tipo === "whatsapp_modelo" ? "Enviado para aprovação da Meta" : "Rascunho criado"} em {action.criado.label}{action.criado.name ? `: ${action.criado.name}` : ""}.
      <button type="button" className="miaGhost" onClick={() => openCreated(action)}>Abrir <ArrowRight size={14} aria-hidden="true" /></button>
    </p>
    {action.tipo === "email" && action.status === "criado" && action.criado?.espacos ? <small className="miaHint">
      Fotos: {action.criado.fotos || 0} de {action.criado.espacos} vieram da Biblioteca (Produto e Fotos da marca).
      {(action.criado.fotos || 0) < action.criado.espacos ? " Os espaços vazios estão marcados no editor para colar o link da foto." : ""}
    </small> : null}</> : canCreate ? <div className="miaCreateRow">
      <button type="button" className="ds-button ds-button--primary" disabled={busy || !messageId} onClick={() => void create()}>
        {busy ? (action.tipo === "whatsapp_modelo" ? "Enviando para a Meta…" : "Criando o rascunho…") : kind.button}</button>
      <small>{action.tipo === "whatsapp_modelo" ? "A Meta aprova o modelo; o disparo para a base continua com vocês em Disparos em massa."
        : "Vira rascunho para revisar. Nada é enviado nem publicado sem vocês."}</small>
    </div> : <small className="miaHint">Quem administra a marca pode criar este rascunho.</small>}
    {error ? <p role="alert" className="studioError">{error}</p> : null}
  </section>;
}
