import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  createClientInvitation,
  createCompanyActivationLink,
  deletePlatformCompany,
  listPlatformCompanies,
  updatePlatformCompany,
  type PlatformCompany,
} from "../app/api";
import { getActiveClient } from "../app/activeClient";
import type { AppRoute } from "../app/routes";
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from "../app/roles";
import CompanyEditDrawer from "../components/admin/CompanyEditDrawer";
import CompanyWizard from "../components/admin/CompanyWizard";
import Modal from "../components/Modal";
import StatusBadge from "../components/StatusBadge";
import "../styles/companies.css";

type Props = {
  onLogout: () => void;
  onOpenCompany: (company: PlatformCompany, targetRoute?: AppRoute) => void;
  onOpenDashboard: () => void;
  /** Só platform_admin cria empresa (mesma autoridade da RPC). Default true p/ compat. */
  canCreateCompany?: boolean;
  /** Exclusão permanente é sempre exclusiva de platform_admin. */
  canDeleteCompany?: boolean;
};

type Tab = "empresas" | "usuarios" | "permissoes";

const TABS: { id: Tab; label: string }[] = [
  { id: "empresas", label: "Empresas" },
  { id: "usuarios", label: "Usuários" },
  { id: "permissoes", label: "Permissões" },
];

const INVITE_ROLES: Array<{ value: "owner" | "agency_admin" | "client_admin" | "viewer"; label: string }> = [
  { value: "viewer", label: "Leitura" },
  { value: "client_admin", label: "Administrador do cliente" },
  { value: "agency_admin", label: "Administrador da agência" },
  { value: "owner", label: "Responsável" },
];

export default function Companies({
  onLogout,
  onOpenCompany,
  onOpenDashboard,
  canCreateCompany = true,
  canDeleteCompany = false,
}: Props) {
  const [companies, setCompanies] = useState<PlatformCompany[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<Tab>("empresas");

  const [wizardOpen, setWizardOpen] = useState(false);
  const [editingCompany, setEditingCompany] = useState<PlatformCompany | null>(null);
  const [deletingCompany, setDeletingCompany] = useState<PlatformCompany | null>(null);
  const [deletionConfirmation, setDeletionConfirmation] = useState("");
  const [deletionLoading, setDeletionLoading] = useState(false);

  const [saving, setSaving] = useState(false);
  const [inviteModalOpen, setInviteModalOpen] = useState(false);
  const [invite, setInvite] = useState({
    client_id: "",
    email: "",
    role: "viewer" as "owner" | "agency_admin" | "client_admin" | "viewer",
  });
  const [inviteMessage, setInviteMessage] = useState("");

  const [activationLink, setActivationLink] = useState<{ url: string; email: string; accountExists: boolean } | null>(null);
  const [activationLoadingId, setActivationLoadingId] = useState<string | null>(null);
  const [activationCopied, setActivationCopied] = useState(false);

  async function generateActivationLink(company: PlatformCompany) {
    setError("");
    setActivationLoadingId(company.id);
    setActivationCopied(false);
    try {
      const response = await createCompanyActivationLink(company.id);
      setActivationLink({
        url: response.activation_url,
        email: response.invitation.email,
        accountExists: response.account_exists,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível gerar o link de ativação.");
    } finally {
      setActivationLoadingId(null);
    }
  }

  async function copyActivationLink() {
    if (!activationLink) return;
    try {
      await navigator.clipboard.writeText(activationLink.url);
      setActivationCopied(true);
    } catch {
      setActivationCopied(false);
    }
  }

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

  function openDeletion(company: PlatformCompany) {
    if (getActiveClient()?.id === company.id) {
      setError("Troque para outra empresa antes de excluir a empresa atualmente aberta.");
      return;
    }
    setError("");
    setDeletionConfirmation("");
    setDeletingCompany(company);
  }

  async function permanentlyDeleteCompany(event: FormEvent) {
    event.preventDefault();
    if (!deletingCompany) return;
    const expectedName = deletingCompany.trade_name || deletingCompany.name;
    if (deletionConfirmation !== expectedName) return;
    if (getActiveClient()?.id === deletingCompany.id) {
      setError("Troque para outra empresa antes de excluir a empresa atualmente aberta.");
      setDeletingCompany(null);
      return;
    }
    setDeletionLoading(true);
    setError("");
    try {
      await deletePlatformCompany(deletingCompany.id, deletionConfirmation);
      setCompanies((current) => current.filter((company) => company.id !== deletingCompany.id));
      setInviteMessage(`A empresa ${expectedName} foi excluída permanentemente.`);
      setDeletingCompany(null);
      setDeletionConfirmation("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível excluir a empresa.");
    } finally {
      setDeletionLoading(false);
    }
  }

  async function submitInvitation(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setInviteMessage("");
    try {
      const response = await createClientInvitation(invite);
      setInvite((current) => ({ ...current, email: "" }));
      setInviteModalOpen(false);
      setInviteMessage(
        response.invitation?.account_exists
          ? "Convite registrado. O e-mail já tem conta Mugô — gere o link de onboarding para ele confirmar o acesso."
          : "Convite enviado com segurança."
      );
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
          <h1>Central de empresas</h1>
          <p>Cadastre tenants, acompanhe convites e gerencie permissões em um só lugar.</p>
        </div>
        <div className="companiesActions">
          <button className="btn" onClick={onOpenDashboard}>Dashboard</button>
          <button className="btn" onClick={onLogout}>Sair</button>
          {canCreateCompany ? (
            <button className="btn btnPrimary" onClick={() => setWizardOpen(true)}>+ Nova empresa</button>
          ) : null}
        </div>
      </header>

      <div className="companiesSummaryRow">
        <div className="companiesSummaryCard"><span>Empresas ativas</span><strong>{summary.active}</strong></div>
        <div className="companiesSummaryCard"><span>Total de empresas</span><strong>{summary.total}</strong></div>
        <div className="companiesSummaryCard"><span>Convites pendentes</span><strong>{summary.pendingInvites}</strong></div>
      </div>

      <nav className="companiesTabs" aria-label="Seções de administração">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`companiesTab${tab === item.id ? " is-active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {error ? <p className="companiesError" role="alert">{error}</p> : null}
      {inviteMessage ? <p className="companiesSuccess" role="status">{inviteMessage}</p> : null}

      {tab === "empresas" ? (
        <section className="companiesCard">
          <div className="companiesListTitle">
            <h2>Empresas cadastradas</h2>
            <div className="companiesActions">
              <button className="btn" onClick={() => void load()} disabled={loading}>Atualizar</button>
              <button className="btn" onClick={() => { setInviteMessage(""); setInviteModalOpen(true); }}>Convidar usuário</button>
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

          {loading ? (
            <div className="companiesSkeletonTable" aria-label="Carregando empresas">
              <div className="skeleton companiesSkeletonRow" />
              <div className="skeleton companiesSkeletonRow" />
              <div className="skeleton companiesSkeletonRow" />
            </div>
          ) : filteredCompanies.length === 0 ? (
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
                      <details className="companiesRowMenu">
                        <summary aria-label={`Mais ações para ${company.trade_name || company.name}`}>⋯</summary>
                        <div className="companiesRowMenuList" role="menu">
                          <button type="button" role="menuitem" onClick={() => onOpenCompany(company, "integrations")}>Fazer onboarding</button>
                          <button type="button" role="menuitem" onClick={() => onOpenCompany(company)}>Abrir para suporte</button>
                          <button
                            type="button"
                            role="menuitem"
                            disabled={activationLoadingId === company.id}
                            onClick={() => void generateActivationLink(company)}
                          >
                            {activationLoadingId === company.id ? "Gerando link..." : "Gerar link de onboarding"}
                          </button>
                          <button type="button" role="menuitem" onClick={() => setEditingCompany(company)}>Editar</button>
                          <button type="button" role="menuitem" onClick={() => void toggleCompanyStatus(company)}>
                            {company.status === "inactive" ? "Ativar" : "Inativar"}
                          </button>
                          {canDeleteCompany ? (
                            <>
                              <div className="companiesRowMenuDivider" />
                              <button
                                type="button"
                                role="menuitem"
                                className="companiesDangerAction"
                                onClick={() => openDeletion(company)}
                              >
                                Excluir permanentemente
                              </button>
                            </>
                          ) : null}
                        </div>
                      </details>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {tab === "usuarios" ? (
        <section className="companiesCard">
          <div className="companiesListTitle">
            <h2>Responsáveis e convites</h2>
          </div>
          <p className="wizardHint">
            Lista com base no responsável cadastrado de cada empresa. Um diretório completo de todos os
            membros por empresa ainda não está disponível nesta tela.
          </p>
          {companies.length === 0 ? (
            <p className="companiesEmptyState">Nenhuma empresa cadastrada ainda.</p>
          ) : (
            <div className="companiesTableWrap">
              <table className="companiesTable">
                <thead><tr><th>E-mail</th><th>Empresa</th><th>Convite</th></tr></thead>
                <tbody>{companies.map((company) => (
                  <tr key={company.id}>
                    <td>{company.responsible_email || "—"}</td>
                    <td>{company.trade_name || company.name}</td>
                    <td>
                      <StatusBadge
                        label={company.invitation_status === "accepted" ? "Aceito" : "Pendente"}
                        tone={company.invitation_status === "accepted" ? "success" : "warning"}
                      />
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {tab === "permissoes" ? (
        <section className="companiesCard">
          <div className="companiesListTitle">
            <h2>Papéis de acesso</h2>
          </div>
          <div className="rolesGrid">
            {(["agency_admin", "client_admin", "viewer"] as const).map((role) => (
              <article className="rolesCard" key={role}>
                <span>{ROLE_LABELS[role]}</span>
                <p>{ROLE_DESCRIPTIONS[role]}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {canCreateCompany ? (
        <CompanyWizard
          open={wizardOpen}
          onClose={() => setWizardOpen(false)}
          onCreated={() => void load()}
          onOpenCompany={onOpenCompany}
        />
      ) : null}

      <CompanyEditDrawer
        company={editingCompany}
        onClose={() => setEditingCompany(null)}
        onSaved={() => { void load(); setEditingCompany(null); }}
      />

      <Modal
        open={Boolean(deletingCompany)}
        title="Excluir empresa permanentemente"
        onClose={() => { if (!deletionLoading) setDeletingCompany(null); }}
      >
        {deletingCompany ? (
          <form className="companiesForm companiesDangerForm" onSubmit={permanentlyDeleteCompany}>
            <p className="companiesDangerWarning">
              Esta ação é irreversível. Ela remove dados, integrações, histórico, memberships e convites
              desta empresa. Os usuários continuam existindo caso tenham acesso a outras empresas.
            </p>
            <p>
              Para confirmar, digite exatamente <strong>{deletingCompany.trade_name || deletingCompany.name}</strong>.
            </p>
            <label>
              Nome da empresa
              <input
                autoComplete="off"
                value={deletionConfirmation}
                onChange={(event) => setDeletionConfirmation(event.target.value)}
              />
            </label>
            {error ? <p className="companiesError" role="alert">{error}</p> : null}
            <div className="companiesRowActions">
              <button type="button" className="btn" disabled={deletionLoading} onClick={() => setDeletingCompany(null)}>
                Cancelar
              </button>
              <button
                type="submit"
                className="btn companiesDangerButton"
                disabled={
                  deletionLoading ||
                  deletionConfirmation !== (deletingCompany.trade_name || deletingCompany.name)
                }
              >
                {deletionLoading ? "Excluindo..." : "Excluir permanentemente"}
              </button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(activationLink)}
        title="Link de ativação do cliente"
        onClose={() => { setActivationLink(null); setActivationCopied(false); }}
      >
        {activationLink ? (
          <div className="companiesForm">
            <p>
              Envie este link para <strong>{activationLink.email}</strong>.{" "}
              {activationLink.accountExists
                ? "O responsável já tem conta Mugô: o link faz login e pede a confirmação do convite desta empresa. As demais empresas dele continuam disponíveis."
                : "Ao abrir, o responsável cria a conta e entra automaticamente na empresa."}
            </p>
            <label>Link
              <input type="text" readOnly value={activationLink.url} onFocus={(event) => event.target.select()} />
            </label>
            <div className="companiesRowActions">
              <button type="button" className="btn btnPrimary" onClick={() => void copyActivationLink()}>
                {activationCopied ? "Link copiado" : "Copiar link"}
              </button>
              <button type="button" className="btn" onClick={() => { setActivationLink(null); setActivationCopied(false); }}>
                Fechar
              </button>
            </div>
          </div>
        ) : null}
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
              {INVITE_ROLES.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <p className="wizardHint">{ROLE_DESCRIPTIONS[invite.role]}</p>
          {error && inviteModalOpen && <p className="companiesError" role="alert">{error}</p>}
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
