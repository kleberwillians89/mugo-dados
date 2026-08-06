import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  createClientInvitation,
  createPlatformCompany,
  listPlatformCompanies,
  updatePlatformCompany,
  type PlatformCompany,
} from "../app/api";
import Modal from "../components/Modal";
import StatusBadge from "../components/StatusBadge";
import "../styles/companies.css";

type Props = {
  onLogout: () => void;
  onOpenCompany: (company: PlatformCompany) => void;
  onOpenDashboard: () => void;
};

const EMPTY_COMPANY_FORM = { name: "", trade_name: "", cnpj: "", responsible_email: "" };

export default function Companies({ onLogout, onOpenCompany, onOpenDashboard }: Props) {
  const [companies, setCompanies] = useState<PlatformCompany[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  const [companyModalOpen, setCompanyModalOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_COMPANY_FORM);

  const [inviteModalOpen, setInviteModalOpen] = useState(false);
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

  const filteredCompanies = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return companies;
    return companies.filter((company) =>
      String(company.trade_name || "").toLowerCase().includes(needle) ||
      String(company.name || "").toLowerCase().includes(needle) ||
      String(company.responsible_email || "").toLowerCase().includes(needle)
    );
  }, [companies, search]);

  const summary = useMemo(() => ({
    total: companies.length,
    active: companies.filter((c) => c.status !== "inactive").length,
    pendingInvites: companies.filter((c) => c.invitation_status === "pending" || !c.invitation_status).length,
  }), [companies]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await createPlatformCompany(form);
      setForm(EMPTY_COMPANY_FORM);
      setCompanyModalOpen(false);
      await load();
    } catch (cause) {
      // Fecha somente em sucesso — em erro, o modal e o formulário
      // preenchido permanecem para o usuário corrigir sem redigitar.
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
      setInviteModalOpen(false);
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

      <div className="companiesSummaryRow">
        <div className="companiesSummaryCard"><span>Empresas</span><strong>{summary.total}</strong></div>
        <div className="companiesSummaryCard"><span>Ativas</span><strong>{summary.active}</strong></div>
        <div className="companiesSummaryCard"><span>Convites pendentes</span><strong>{summary.pendingInvites}</strong></div>
      </div>

      <section className="companiesCard">
        <div className="companiesListTitle">
          <h2>Empresas cadastradas</h2>
          <div className="companiesActions">
            <button className="btn" onClick={() => void load()} disabled={loading}>Atualizar</button>
            <button className="btn" onClick={() => { setInviteMessage(""); setInviteModalOpen(true); }}>Convidar usuário</button>
            <button className="btn btnPrimary" onClick={() => { setError(""); setCompanyModalOpen(true); }}>Nova empresa</button>
          </div>
        </div>

        <div className="companiesSearchRow">
          <input
            type="search"
            placeholder="Buscar por nome ou e-mail do responsável..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Buscar empresas"
          />
        </div>

        {error && !companyModalOpen && !inviteModalOpen && <p className="companiesError" role="alert">{error}</p>}
        {inviteMessage && <p className="companiesSuccess" role="status">{inviteMessage}</p>}

        {loading ? <p>Carregando...</p> : filteredCompanies.length === 0 ? (
          <p className="companiesEmptyState">
            {companies.length === 0 ? "Nenhuma empresa cadastrada ainda." : "Nenhuma empresa corresponde à busca."}
          </p>
        ) : (
          <div className="companiesTableWrap">
            <table className="companiesTable">
              <thead><tr><th>Empresa</th><th>Responsável</th><th>Status</th><th>Convite</th><th /></tr></thead>
              <tbody>{filteredCompanies.map((company) => (
                <tr key={company.id}>
                  <td><strong>{company.trade_name || company.name}</strong><small>{company.name}</small></td>
                  <td>{company.responsible_email || "—"}</td>
                  <td>
                    <StatusBadge
                      label={company.status === "inactive" ? "Inativa" : "Ativa"}
                      tone={company.status === "inactive" ? "neutral" : "success"}
                    />
                  </td>
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

      <Modal open={companyModalOpen} title="Nova empresa" onClose={() => { if (!saving) setCompanyModalOpen(false); }}>
        <form className="companiesForm" onSubmit={submit}>
          <label>Razão social<input required minLength={2} value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>Nome fantasia<input value={form.trade_name}
            onChange={(e) => setForm({ ...form, trade_name: e.target.value })} /></label>
          <label>CNPJ (opcional)<input inputMode="numeric" value={form.cnpj}
            onChange={(e) => setForm({ ...form, cnpj: e.target.value })} /></label>
          <label>E-mail do responsável<input required type="email" value={form.responsible_email}
            onChange={(e) => setForm({ ...form, responsible_email: e.target.value })} /></label>
          {error && <p className="companiesError" role="alert">{error}</p>}
          <div className="companiesRowActions">
            <button type="button" className="btn" disabled={saving} onClick={() => setCompanyModalOpen(false)}>Cancelar</button>
            <button className="btn btnPrimary" disabled={saving}>
              {saving ? "Criando e convidando..." : "Criar empresa"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal open={inviteModalOpen} title="Convidar usuário" onClose={() => { if (!saving) setInviteModalOpen(false); }}>
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
          {error && <p className="companiesError" role="alert">{error}</p>}
          <div className="companiesRowActions">
            <button type="button" className="btn" disabled={saving} onClick={() => setInviteModalOpen(false)}>Cancelar</button>
            <button className="btn btnPrimary" disabled={saving || !invite.client_id}>
              {saving ? "Enviando..." : "Enviar convite"}
            </button>
          </div>
        </form>
      </Modal>
    </main>
  );
}
