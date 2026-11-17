import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../app/api";
import { connectWhatsAppNumber, disconnectWhatsAppNumber, listWhatsAppNumbers, getWhatsAppConnectionStatus, type WaNumber, type WaConnectionStatus } from "../../app/whatsapp";

/**
 * Números de WhatsApp da empresa ligados direto no MUGOVERSO (app da Mugô na Meta).
 * Só aparece para a agência: o backend recusa os demais e o painel some.
 * O token é enviado uma vez e nunca volta para a tela.
 */
export default function WhatsAppNumbers({ onChange }: { onChange?: () => void }) {
  const [numbers, setNumbers] = useState<WaNumber[] | null>(null);
  const [connection, setConnection] = useState<WaConnectionStatus | null>(null);
  const [allowed, setAllowed] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ waba_id: "", phone_number_id: "", access_token: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([listWhatsAppNumbers(), getWhatsAppConnectionStatus()])
      .then(([res, status]) => { if (alive) { setNumbers(res.numbers); setConnection(status); } })
      .catch(() => { if (alive) setAllowed(false); });
    return () => { alive = false; };
  }, []);

  if (!allowed) return null;
  const active = (numbers || []).filter((n) => n.status === "active");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await connectWhatsAppNumber({
        waba_id: form.waba_id.trim(), phone_number_id: form.phone_number_id.trim(), access_token: form.access_token.trim(),
      });
      setNumbers((current) => [...(current || []).filter((n) => n.id !== res.number.id), res.number]);
      setForm({ waba_id: "", phone_number_id: "", access_token: "" });
      setOpen(false);
      onChange?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Não foi possível ligar o número agora.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(number: WaNumber) {
    if (!window.confirm(`Desligar ${number.display_phone_number || "este número"} do MUGOVERSO? As conversas já gravadas ficam.`)) return;
    try {
      await disconnectWhatsAppNumber(number.id);
      setNumbers((current) => (current || []).map((n) => (n.id === number.id ? { ...n, status: "disconnected" } : n)));
      onChange?.();
    } catch {
      setError("Não foi possível desligar agora.");
    }
  }

  return (
    <section className="waCard" aria-labelledby="wa-numbers">
      <div className="waCardHead">
        <h2 id="wa-numbers">Número de WhatsApp da marca</h2>
        <span className="waMuted">só a agência vê esta parte</span>
      </div>
      {connection ? <div className="waConnectionSummary" role="status">
        <strong>{connection.provider === "native" ? "Cloud API conectada" :
          connection.provider === "crm_bridge" ? "Conectado via CRM próprio" : "WhatsApp não conectado"}</strong>
        <span>{connection.notice}</span>
        <small>Credencial da Meta: {connection.meta_credentials_saved ? "Configurada e protegida" :
          "Ainda não cadastrada nesta empresa"} · {connection.number_count} número(s) Cloud API ativo(s)</small>
        {connection.provider === "crm_bridge" && !connection.native_connected ?
          <small>Para criar modelos diretamente pela Meta, conecte uma WABA e seu número oficial. A chave da ponte CRM não é um token Meta.</small> : null}
      </div> : null}
      {active.length ? (
        <ul className="waNumbers">
          {active.map((n) => (
            <li key={n.id}>
              <span><b>{n.display_phone_number || n.phone_number_id}</b>{n.verified_name ? ` · ${n.verified_name}` : ""}
                <small>Recebendo mensagens pelo app da Mugô{n.subscribed_at ? ` desde ${new Date(n.subscribed_at).toLocaleDateString("pt-BR")}` : ""}</small></span>
              <button type="button" className="waLinkButton" onClick={() => void disconnect(n)}>Desligar</button>
            </li>
          ))}
        </ul>
      ) : numbers ? <p className="waMuted">Nenhum número ligado direto no MUGOVERSO.</p> : null}

      {!open ? (
        <button type="button" className="waPrimary" onClick={() => setOpen(true)}>{active.length ? "Ligar outro número" : "Ligar número"}</button>
      ) : (
        <form className="waForm" onSubmit={(e) => void submit(e)}>
          <p className="waMuted">Os dados pertencem exclusivamente à empresa selecionada. Copie WABA ID e Phone Number ID do gerenciador da Meta e cadastre um token de usuário do sistema autorizado para esta WABA. Tokens nunca são exibidos novamente na tela.</p>
          <label>ID da conta do WhatsApp Business (WABA)
            <input inputMode="numeric" autoComplete="off" required value={form.waba_id}
              onChange={(e) => setForm({ ...form, waba_id: e.target.value.replace(/\D/g, "") })} />
          </label>
          <label>ID do número de telefone
            <input inputMode="numeric" autoComplete="off" required value={form.phone_number_id}
              onChange={(e) => setForm({ ...form, phone_number_id: e.target.value.replace(/\D/g, "") })} />
          </label>
          <label>Token de acesso
            <input type="password" autoComplete="off" required value={form.access_token}
              onChange={(e) => setForm({ ...form, access_token: e.target.value })} />
          </label>
          {error ? <p className="waError" role="alert">{error}</p> : null}
          <div className="waFormActions">
            <button type="submit" className="waPrimary" disabled={busy}>{busy ? "Conferindo na Meta…" : "Ligar número"}</button>
            <button type="button" className="waLinkButton" onClick={() => { setOpen(false); setError(""); }}>Cancelar</button>
          </div>
        </form>
      )}
      {error && !open ? <p className="waError" role="alert">{error}</p> : null}
    </section>
  );
}
