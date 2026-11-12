import { useEffect, useState } from "react";
import { getEmailSettings, saveEmailSettings, senderNotice, type EmailSettings, type SenderStatus } from "../../app/emailMarketing";

const FIELDS: { key: keyof EmailSettings; label: string; placeholder: string; hint?: string }[] = [
  { key: "from_name", label: "Nome do remetente", placeholder: "Roove" },
  { key: "from_email", label: "E-mail do remetente", placeholder: "contato@roove.com.br", hint: "O domínio precisa estar verificado no Resend." },
  { key: "reply_to", label: "Responder para", placeholder: "atendimento@roove.com.br" },
  { key: "store_url", label: "Link da loja", placeholder: "https://roove.com.br", hint: "Usado no {{link_loja}}." },
  { key: "logo_url", label: "Logo (link da imagem)", placeholder: "https://…/logo.png" },
  { key: "brand_color", label: "Cor dos botões", placeholder: "#1e3f5a" },
];

export default function SenderPanel({ canEdit, onStatus }: { canEdit: boolean; onStatus?: (status: SenderStatus) => void }) {
  const [settings, setSettings] = useState<EmailSettings | null>(null);
  const [status, setStatus] = useState<SenderStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    getEmailSettings().then((out) => { if (alive) { setSettings(out.settings); setStatus(out.status); onStatus?.(out.status); } })
      .catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "Não foi possível ler o remetente."); });
    return () => { alive = false; };
  }, [onStatus]);

  async function save() {
    if (!settings) return;
    setSaving(true); setError(""); setMessage("");
    try {
      const out = await saveEmailSettings(settings);
      setSettings(out.settings); setStatus(out.status); onStatus?.(out.status);
      setMessage("Remetente salvo.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível salvar.");
    } finally {
      setSaving(false);
    }
  }

  if (!settings) return error ? <p className="emError" role="alert">{error}</p> : <p className="emMuted">Carregando remetente…</p>;
  const notice = senderNotice(status);
  return (
    <section className="emCard emSender">
      <header className="emCardHead">
        <div>
          <h2>Remetente</h2>
          <p className="emMuted">De quem o cliente recebe os e-mails desta marca (campanhas e carrinho abandonado).</p>
        </div>
        {status ? <span className={`emPill ${status.ready ? "is-ok" : "is-warn"}`}>{status.ready ? "Pronto para enviar" : "Falta configurar"}</span> : null}
      </header>
      {notice ? <p className="emNotice">{notice}</p> : null}
      <div className="emFormGrid">
        {FIELDS.map((field) => (
          <label key={field.key} className="emField">
            <span>{field.label}</span>
            <input value={settings[field.key] || ""} placeholder={field.placeholder} disabled={!canEdit}
              onChange={(e) => setSettings({ ...settings, [field.key]: e.target.value })} />
            {field.hint ? <small>{field.hint}</small> : null}
          </label>
        ))}
        <label className="emField is-wide">
          <span>Rodapé</span>
          <textarea rows={2} value={settings.footer_text || ""} disabled={!canEdit} placeholder="Roove · Rua Exemplo, 100 · São Paulo/SP"
            onChange={(e) => setSettings({ ...settings, footer_text: e.target.value })} />
          <small>O link “Não quero mais receber” entra sempre, automaticamente.</small>
        </label>
      </div>
      {error ? <p className="emError" role="alert">{error}</p> : null}
      {canEdit ? (
        <div className="emActions">
          {message ? <span className="emOk">{message}</span> : null}
          <button type="button" className="ds-button is-primary" onClick={() => void save()} disabled={saving}>{saving ? "Salvando…" : "Salvar remetente"}</button>
        </div>
      ) : null}
    </section>
  );
}
