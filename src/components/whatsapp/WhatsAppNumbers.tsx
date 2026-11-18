import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../app/api";
import { connectWhatsAppNumber, disconnectWhatsAppNumber, listWhatsAppNumbers, getWhatsAppConnectionStatus, getRooveMetaRegistrationStatus, registerRooveMetaNumber, type WaMetaRegistration, type WaNumber, type WaConnectionStatus } from "../../app/whatsapp";

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
  const [form, setForm] = useState({ waba_id: "", phone_number_id: "", access_token: "", meta_app_id: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [metaState, setMetaState] = useState<WaMetaRegistration | null>(null);
  const [metaBusy, setMetaBusy] = useState(false);
  const [registrationPin, setRegistrationPin] = useState("");
  const rooveNumber = (numbers || []).find((n) => n.status === "active" && n.phone_number_id === "1063683626819387" && n.meta_app_id === "1161210926623351");

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
        waba_id: form.waba_id.trim(), phone_number_id: form.phone_number_id.trim(), access_token: form.access_token.trim(), meta_app_id: form.meta_app_id.trim() || null,
      });
      setNumbers((current) => [...(current || []).filter((n) => n.id !== res.number.id), res.number]);
      setForm({ waba_id: "", phone_number_id: "", access_token: "", meta_app_id: "" });
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

  async function checkMetaRegistration() {
    if (!rooveNumber) return;
    setMetaBusy(true); setMetaState(null); setRegistrationPin(""); setError("");
    try {
      setMetaState(await getRooveMetaRegistrationStatus(rooveNumber.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Não foi possível consultar o status na Meta.");
    } finally { setMetaBusy(false); }
  }

  async function registerAtMeta(event: FormEvent) {
    event.preventDefault();
    if (!rooveNumber || !metaState?.can_register || !/^[0-9]{6}$/.test(registrationPin) || metaBusy) return;
    const accepted = window.confirm(
      "Confirmar registro na Meta APENAS do número secundário +55 11 94470-6392 (Roove)? " +
      "Esta ação altera o estado do número na Cloud API. O número principal não será alterado."
    );
    if (!accepted) return;
    setMetaBusy(true); setError("");
    try {
      const outcome = await registerRooveMetaNumber(rooveNumber.id, registrationPin, true);
      setMetaState(null); // Força uma nova consulta à Meta, nunca presume Connected.
      if (outcome.registration_requested || outcome.already_connected) {
        setError("A Meta recebeu o registro. Clique em 'Consultar status na Meta' para confirmar Connected.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "A Meta não confirmou o registro. Não tente repetidamente.");
    } finally {
      setRegistrationPin("");
      setMetaBusy(false);
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
          connection.provider === "crm_bridge" ? "WhatsApp conectado via CRM próprio" :
          connection.provider === "mugozap_crm" ? "WhatsApp conectado via MugôZap" :
          connection.crm_status_unavailable ? "Conexão com CRM não verificada" : "WhatsApp não conectado"}</strong>
        <span>{connection.notice}</span>
        <small>{connection.native_connected
          ? `Credencial Meta protegida · ${connection.number_count} número(s) Cloud API`
          : connection.connected
          ? "Conexão existente preservada. Credenciais do CRM protegidas no backend; não é necessário reconectar para acessar mensagens."
          : "Nenhuma credencial Meta nativa cadastrada nesta empresa."}</small>
        {connection.connected && !connection.native_connected ?
          <small>As mensagens já funcionam pelo CRM. A criação de modelos diretamente na Meta requer uma WABA vinculada ou suporte de templates pela ponte, sem substituir a conexão atual.</small> : null}
      </div> : null}
      {active.length ? (
        <ul className="waNumbers">
          {active.map((n) => (
            <li key={n.id}>
              <span><b>{n.display_phone_number || n.phone_number_id}</b>{n.verified_name ? ` · ${n.verified_name}` : ""}
                <small>Recebendo mensagens pelo {n.meta_app_id ? `Meta App ${n.meta_app_id}` : "app da Mugô"}{n.subscribed_at ? ` desde ${new Date(n.subscribed_at).toLocaleDateString("pt-BR")}` : ""}</small></span>
              <button type="button" className="waLinkButton" onClick={() => void disconnect(n)}>Desligar</button>
            </li>
          ))}
        </ul>
      ) : numbers && !connection?.connected ? <p className="waMuted">Nenhum número Cloud API ligado diretamente ao Mugô Dados.</p> : null}

      {rooveNumber ? (
        <div className="waConnectionSummary">
          <strong>Registro Cloud API — número secundário Roove</strong>
          <p className="waMuted">O status “active” deste painel é interno. Consulte o registro real na Meta antes de tentar ativar.</p>
          <button type="button" className="waLinkButton" onClick={() => void checkMetaRegistration()} disabled={metaBusy}>
            {metaBusy ? "Consultando…" : "Consultar status na Meta"}
          </button>
          {metaState ? (
            <div role="status">
              <p>Status Meta: <strong>{metaState.status || "Indisponível"}</strong> · Verificação: {metaState.code_verification_status || "—"}</p>
              {metaState.registered ? <p>Número registrado na Cloud API. Faça um teste de recebimento.</p> : null}
              {!metaState.registered && !metaState.can_register ? <p>Registro bloqueado: estado desconhecido ou incompatível. Confira com a Meta.</p> : null}
              {metaState.can_register ? (
                <form className="waForm" onSubmit={(e) => void registerAtMeta(e)}>
                  <p className="waMuted">Ação opcional, nunca automática. PIN de seis dígitos usado uma única vez e não salvo. Não informe PIN de SMS ou código de login.</p>
                  <label>PIN da verificação em duas etapas da Cloud API
                    <input type="password" inputMode="numeric" autoComplete="off" maxLength={6} pattern="[0-9]{6}" required
                      value={registrationPin} onChange={(e) => setRegistrationPin(e.target.value.replace(/\\D/g, "").slice(0, 6))} />
                  </label>
                  <button type="submit" className="waPrimary" disabled={metaBusy || registrationPin.length !== 6}>
                    Registrar número na Meta (exige confirmação)
                  </button>
                </form>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {!open ? (
        <button type="button" className="waPrimary" onClick={() => setOpen(true)}>{active.length ? "Ligar outro número" : connection?.connected ? "Adicionar Cloud API (opcional)" : "Ligar número"}</button>
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
          <label>ID do Meta App (opcional, use para ROOVEWHATS ou apps de clientes)
            <input inputMode="numeric" autoComplete="off" value={form.meta_app_id}
              onChange={(e) => setForm({ ...form, meta_app_id: e.target.value.replace(/\D/g, "") })} />
          </label>
          <p className="waMuted">Para ROOVEWHATS, use o App ID 1161210926623351. Para a conexão legada da Mugô, deixe vazio. Configure o webhook deste App no Supabase do Mugô Dados.</p>
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
