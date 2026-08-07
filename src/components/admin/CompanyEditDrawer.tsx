import { useState } from "react";
import { updatePlatformCompany, type PlatformCompany } from "../../app/api";
import Drawer from "../Drawer";

type Props = {
  company: PlatformCompany | null;
  onClose: () => void;
  onSaved: (company: PlatformCompany) => void;
};

export default function CompanyEditDrawer({ company, onClose, onSaved }: Props) {
  const [form, setForm] = useState<{ name: string; trade_name: string; cnpj: string; status: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedMessage, setSavedMessage] = useState("");

  const active = form
    ? form
    : company
      ? { name: company.name, trade_name: company.trade_name || "", cnpj: company.cnpj || "", status: company.status }
      : null;

  function handleClose() {
    if (saving) return;
    setForm(null);
    setError("");
    setSavedMessage("");
    onClose();
  }

  async function submit() {
    if (!company || !active) return;
    setSaving(true);
    setError("");
    setSavedMessage("");
    try {
      const response = await updatePlatformCompany(company.id, {
        name: active.name,
        trade_name: active.trade_name,
        cnpj: active.cnpj,
        status: active.status,
      });
      onSaved(response.company);
      setSavedMessage("Alterações salvas.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível salvar as alterações.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer
      open={Boolean(company)}
      title={company ? company.trade_name || company.name : "Editar empresa"}
      description="Geral"
      onClose={handleClose}
      footer={
        <>
          <button type="button" className="btn" disabled={saving} onClick={handleClose}>Cancelar</button>
          <button type="button" className="btn btnPrimary" disabled={saving || !active} onClick={() => void submit()}>
            {saving ? "Salvando..." : "Salvar alterações"}
          </button>
        </>
      }
    >
      {active ? (
        <div className="wizardPane">
          <label>Razão social
            <input required minLength={2} value={active.name}
              onChange={(e) => setForm({ ...active, name: e.target.value })} />
          </label>
          <label>Nome fantasia
            <input value={active.trade_name}
              onChange={(e) => setForm({ ...active, trade_name: e.target.value })} />
          </label>
          <label>CNPJ
            <input inputMode="numeric" value={active.cnpj}
              onChange={(e) => setForm({ ...active, cnpj: e.target.value })} />
          </label>
          <label>Status
            <select value={active.status} onChange={(e) => setForm({ ...active, status: e.target.value })}>
              <option value="active">Ativa</option>
              <option value="inactive">Inativa</option>
            </select>
          </label>
          {error ? <p className="wizardError" role="alert">{error}</p> : null}
          {savedMessage ? <p className="companiesSuccess" role="status">{savedMessage}</p> : null}
        </div>
      ) : null}
    </Drawer>
  );
}
