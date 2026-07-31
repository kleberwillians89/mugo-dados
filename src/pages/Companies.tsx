import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  createClientInvitation,
  createPlatformCompany,
  listPlatformCompanies,
  updatePlatformCompany,
  type PlatformCompany,
} from "../app/api";
import "../styles/companies.css";

type Props = {
  onLogout: () => void;
  onOpenCompany: (company: PlatformCompany) => void;
  onOpenDashboard: () => void;
};

export default function Companies({ onLogout, onOpenCompany, onOpenDashboard }: Props) {
  const [companies, setCompanies] = useState<PlatformCompany[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    name: "", trade_name: "", cnpj: "", responsible_email: "",
  });
  const [invite, setInvite] = useState({
    client_id: "",
    email: "",
    role: "viewer" as "owner" | "agency_admin" | "client_admin" | "viewer",
  });
  const [inviteMessage, setInviteMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCompanies((await listPlatformCompanies()).companies || []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível carregar as empresas.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await createPlatformCompany(form);
      setForm({ name: "", trade_name: "", cnpj: "", responsible_email: "" });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível criar a empresa.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleCompanyStatus(company: PlatformCompany) {
    setError("");
    try {
      await updatePlatformCompany(company.id, {
        status: company.status === "inactive" ? "active" : "inactive",
      });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível atualizar a empresa.");
    }
  }

  async function submitInvitation(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setInviteMessage("");
    try {
      await createClientInvitation(invite);
      setInvite((current) => ({ ...current, email: "" }));
      setInviteMessage("Convite enviado com segurança.");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível enviar o convite.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="companiesPage">
      <header className="companiesHeader">
        <div>
          <span className="companiesEyebrow">Administração da plataforma</span>
          <h1>Empresas</h1>
          <p>Cadastre tenants e acompanhe o convite do primeiro responsável.</p>
        </div>
        <div className="companiesActions">
          <button className="btn" onClick={onOpenDashboard}>Dashboard</button>
          <button className="btn" onClick={onLogout}>Sair</button>
        </div>
      </header>

      <section className="companiesCard">
        <h2>Nova empresa</h2>
        <form className="companiesForm" onSubmit={submit}>
          <label>Razão social<input required minLength={2} value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>Nome fantasia<input value={form.trade_name}
            onChange={(e) => setForm({ ...form, trade_name: e.target.value })} /></label>
          <label>CNPJ (opcional)<input inputMode="numeric" value={form.cnpj}
            onChange={(e) => setForm({ ...form, cnpj: e.target.value })} /></label>
          <label>E-mail do responsável<input required type="email" value={form.responsible_email}
            onChange={(e) => setForm({ ...form, responsible_email: e.target.value })} /></label>
          <button className="btn btnPrimary" disabled={saving}>
            {saving ? "Criando e convidando..." : "Criar empresa"}
          </button>
        </form>
        {error && <p className="companiesError" role="alert">{error}</p>}
      </section>

      <section className="companiesCard">
        <h2>Convidar usuário</h2>
        <p>O acesso será limitado à empresa e ao papel selecionados.</p>
        <form className="companiesForm" onSubmit={submitInvitation}>
          <label>Empresa
            <select required value={invite.client_id}
              onChange={(event) => setInvite({ ...invite, client_id: event.target.value })}>
              <option value="">Selecione</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.trade_name || company.name}
                </option>
              ))}
            </select>
          </label>
          <label>E-mail<input required type="email" value={invite.email}
            onChange={(event) => setInvite({ ...invite, email: event.target.value })} /></label>
          <label>Papel
            <select value={invite.role}
              onChange={(event) => setInvite({
                ...invite,
                role: event.target.value as typeof invite.role,
              })}>
              <option value="viewer">Leitura</option>
              <option value="client_admin">Administrador do cliente</option>
              <option value="agency_admin">Administrador da agência</option>
              <option value="owner">Responsável</option>
            </select>
          </label>
          <button className="btn btnPrimary" disabled={saving || !invite.client_id}>
            {saving ? "Enviando..." : "Enviar convite"}
          </button>
        </form>
        {inviteMessage && <p className="companiesSuccess" role="status">{inviteMessage}</p>}
      </section>

      <section className="companiesCard">
        <div className="companiesListTitle">
          <h2>Empresas cadastradas</h2>
          <button className="btn" onClick={() => void load()} disabled={loading}>Atualizar</button>
        </div>
        {loading ? <p>Carregando...</p> : (
          <div className="companiesTableWrap">
            <table className="companiesTable">
              <thead><tr><th>Empresa</th><th>Responsável</th><th>Status</th><th>Convite</th><th /></tr></thead>
              <tbody>{companies.map((company) => (
                <tr key={company.id}>
                  <td><strong>{company.trade_name || company.name}</strong><small>{company.name}</small></td>
                  <td>{company.responsible_email || "—"}</td>
                  <td><span className="companiesStatus">{company.status}</span></td>
                  <td>{company.invitation_status || "—"}</td>
                  <td>
                    <div className="companiesRowActions">
                      <button className="btn" onClick={() => onOpenCompany(company)}>Abrir para suporte</button>
                      <button className="btn" onClick={() => void toggleCompanyStatus(company)}>
                        {company.status === "inactive" ? "Ativar" : "Inativar"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
