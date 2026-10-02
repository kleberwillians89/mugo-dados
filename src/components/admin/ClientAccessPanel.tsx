import { useCallback, useEffect, useState } from "react";
import {
  createClientAccess,
  listClientAccess,
  removeClientAccess,
  resetClientAccessPassword,
  type ClientAccessItem,
} from "../../app/api";
import { getActiveClientName } from "../../app/activeClient";

/**
 * Acessos da empresa ativa.
 *
 * A empresa vem do contexto autorizado — nenhum `client_id` é enviado. Os
 * perfis oferecidos são só os de cliente; papéis da equipe Mugô não aparecem
 * aqui e o servidor recusa recebê-los. Esconder botão é conveniência: toda
 * ação é revalidada no backend.
 *
 * Senha existe apenas no formulário: ao enviar, o campo é limpo e nada fica
 * em estado, storage ou URL.
 */

const ROLES: Array<{ value: "viewer" | "client_admin"; label: string; hint: string }> = [
  { value: "viewer", label: "Visualizador", hint: "Vê os dados da empresa, sem alterar nada." },
  { value: "client_admin", label: "Administrador do cliente", hint: "Vê os dados e administra integrações e acessos." },
];

const EMPTY_FORM = { name: "", email: "", password: "", password_confirmation: "", role: "viewer" as const };

type Props = {
  /** Perfil de gestão concedido pelo App; o backend valida de novo. */
  canManage?: boolean;
};

function errorText(cause: unknown, fallback: string) {
  if (cause && typeof cause === "object" && "message" in cause) {
    const message = String((cause as { message?: unknown }).message || "").trim();
    if (message) return message;
  }
  return fallback;
}

function formatMoment(value: string | null | undefined) {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime())
    ? "—"
    : parsed.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" });
}

export default function ClientAccessPanel({ canManage = false }: Props) {
  const [items, setItems] = useState<ClientAccessItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<typeof EMPTY_FORM>({ ...EMPTY_FORM });
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<ClientAccessItem | null>(null);
  const [resetForm, setResetForm] = useState({ password: "", password_confirmation: "" });
  const [removing, setRemoving] = useState<ClientAccessItem | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const response = await listClientAccess({ signal });
      if (signal?.aborted) return;
      setItems(response.items);
    } catch (cause) {
      if (signal?.aborted) return;
      setError(errorText(cause, "Não foi possível carregar os acessos desta empresa."));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function resetFeedback() {
    setError("");
    setMessage("");
  }

  async function submitCreate() {
    if (!canManage) return;
    setBusy(true);
    resetFeedback();
    try {
      await createClientAccess({
        name: form.name.trim(),
        email: form.email.trim(),
        password: form.password,
        password_confirmation: form.password_confirmation,
        role: form.role,
      });
      // A senha sai do estado assim que a requisição termina.
      setForm({ ...EMPTY_FORM });
      setCreating(false);
      setMessage("Acesso criado. A pessoa já pode entrar com o e-mail e a senha definidos.");
      await load();
    } catch (cause) {
      setError(errorText(cause, "Não foi possível criar o acesso."));
    } finally {
      setBusy(false);
    }
  }

  async function submitReset() {
    if (!canManage || !resetting) return;
    setBusy(true);
    resetFeedback();
    try {
      await resetClientAccessPassword(resetting.user_id, {
        password: resetForm.password,
        password_confirmation: resetForm.password_confirmation,
      });
      setResetForm({ password: "", password_confirmation: "" });
      setResetting(null);
      setMessage("Senha redefinida. Informe a nova senha à pessoa por um canal seguro.");
    } catch (cause) {
      setError(errorText(cause, "Não foi possível redefinir a senha."));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRemove() {
    if (!canManage || !removing) return;
    setBusy(true);
    resetFeedback();
    try {
      await removeClientAccess(removing.user_id);
      setRemoving(null);
      setMessage("Acesso removido desta empresa. A conta e os acessos a outras empresas continuam.");
      await load();
    } catch (cause) {
      setError(errorText(cause, "Não foi possível remover o acesso."));
    } finally {
      setBusy(false);
    }
  }

  const company = getActiveClientName() || "a empresa ativa";

  return (
    <section className="companiesCard" data-testid="client-access-panel">
      <div className="companiesListTitle">
        <div>
          <h2>Acessos</h2>
          <p className="companiesCardNote">
            Quem entra no Mugô Dados por {company}. Perfis da equipe Mugô são administrados
            em Equipe Mugô.
          </p>
        </div>
        <div className="companiesActions">
          <button className="btn" type="button" disabled={loading || busy} onClick={() => void load()}>
            Atualizar
          </button>
          {canManage ? (
            <button
              className="btn btnPrimary"
              type="button"
              disabled={busy}
              onClick={() => { resetFeedback(); setCreating((value) => !value); }}
            >
              {creating ? "Cancelar" : "Criar acesso"}
            </button>
          ) : null}
        </div>
      </div>

      {error ? <p className="companiesError" role="alert">{error}</p> : null}
      {message ? <p className="companiesSuccess" role="status">{message}</p> : null}
      {!canManage ? (
        <p className="companiesCardNote">
          Você pode consultar os acessos. Criar e alterar é de administradores da empresa.
        </p>
      ) : null}

      {creating && canManage ? (
        <form
          className="accessForm"
          data-testid="client-access-form"
          onSubmit={(event) => { event.preventDefault(); void submitCreate(); }}
        >
          <label>Nome
            <input
              value={form.name}
              autoComplete="off"
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            />
          </label>
          <label>E-mail
            <input
              type="email"
              required
              value={form.email}
              autoComplete="off"
              onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
            />
          </label>
          <label>Senha inicial
            <input
              type="password"
              required
              minLength={8}
              value={form.password}
              autoComplete="new-password"
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
            />
          </label>
          <label>Confirmar senha
            <input
              type="password"
              required
              minLength={8}
              value={form.password_confirmation}
              autoComplete="new-password"
              onChange={(event) => setForm((current) => ({ ...current, password_confirmation: event.target.value }))}
            />
          </label>
          <label>Perfil
            <select
              value={form.role}
              onChange={(event) => setForm((current) => ({ ...current, role: event.target.value as typeof current.role }))}
            >
              {ROLES.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
            </select>
            <span className="accessHint">{ROLES.find((role) => role.value === form.role)?.hint}</span>
          </label>
          <div className="accessFormActions">
            <button className="btn btnPrimary" type="submit" disabled={busy}>
              {busy ? "Criando..." : "Criar acesso"}
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <p className="companiesCardNote" role="status">Carregando acessos...</p>
      ) : items.length === 0 ? (
        <p className="companiesEmptyState">Nenhum acesso nesta empresa ainda.</p>
      ) : (
        <div className="companiesTableWrap">
          <table className="companiesTable accessTable">
            <thead>
              <tr><th>Pessoa</th><th>Perfil</th><th>Status</th><th aria-label="Ações" /></tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.membership_id}>
                  <td>
                    {item.name || item.email || "Sem nome"}
                    <small>{item.email || "E-mail não disponível"}</small>
                  </td>
                  <td>
                    {item.role_label}
                    {item.is_global_role ? <small>Equipe Mugô</small> : null}
                  </td>
                  <td>
                    {item.email_confirmed === false ? "Aguardando confirmação" : "Ativo"}
                    <small>Último acesso: {formatMoment(item.last_sign_in_at)}</small>
                  </td>
                  <td>
                    {canManage && !item.is_global_role ? (
                      <div className="companiesRowActions">
                        <button
                          className="btn"
                          type="button"
                          disabled={busy}
                          onClick={() => { resetFeedback(); setResetting(item); setResetForm({ password: "", password_confirmation: "" }); }}
                        >
                          Redefinir senha
                        </button>
                        <button
                          className="btn"
                          type="button"
                          disabled={busy}
                          onClick={() => { resetFeedback(); setRemoving(item); }}
                        >
                          Remover acesso
                        </button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resetting && canManage ? (
        <form
          className="accessForm"
          data-testid="client-access-reset"
          onSubmit={(event) => { event.preventDefault(); void submitReset(); }}
        >
          <p className="companiesCardNote">
            Nova senha para {resetting.name || resetting.email}. A senha atual não é exibida nem recuperada.
          </p>
          <label>Nova senha
            <input
              type="password"
              required
              minLength={8}
              value={resetForm.password}
              autoComplete="new-password"
              onChange={(event) => setResetForm((current) => ({ ...current, password: event.target.value }))}
            />
          </label>
          <label>Confirmar nova senha
            <input
              type="password"
              required
              minLength={8}
              value={resetForm.password_confirmation}
              autoComplete="new-password"
              onChange={(event) => setResetForm((current) => ({ ...current, password_confirmation: event.target.value }))}
            />
          </label>
          <div className="accessFormActions">
            <button className="btn btnPrimary" type="submit" disabled={busy}>
              {busy ? "Salvando..." : "Definir nova senha"}
            </button>
            <button className="btn" type="button" disabled={busy} onClick={() => setResetting(null)}>Cancelar</button>
          </div>
        </form>
      ) : null}

      {removing && canManage ? (
        <div className="accessConfirm" role="alertdialog" data-testid="client-access-remove">
          <p>
            Remover o acesso de {removing.name || removing.email} a {company}? A conta continua
            existindo e outros acessos dessa pessoa não são afetados.
          </p>
          <div className="accessFormActions">
            <button className="btn btnPrimary" type="button" disabled={busy} onClick={() => void confirmRemove()}>
              {busy ? "Removendo..." : "Remover acesso"}
            </button>
            <button className="btn" type="button" disabled={busy} onClick={() => setRemoving(null)}>Cancelar</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
