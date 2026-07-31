import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  createPlatformCompany,
  listPlatformCompanies,
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
                  <td><button className="btn" onClick={() => onOpenCompany(company)}>Abrir para suporte</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
