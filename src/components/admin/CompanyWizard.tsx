import { useState, useRef } from "react";
import {
  createClientInvitation,
  createPlatformCompany,
  type PlatformCompany,
} from "../../app/api";
import { ROLE_DESCRIPTIONS } from "../../app/roles";
import Drawer from "../Drawer";

type Role = "owner" | "agency_admin" | "client_admin" | "viewer";

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (company: PlatformCompany) => void;
  onOpenCompany: (company: PlatformCompany) => void;
};

const STEPS = ["Dados", "Usuários", "Integrações", "Revisão", "Concluído"] as const;

const EMPTY_COMPANY = { name: "", trade_name: "", cnpj: "", responsible_email: "" };
const EMPTY_INVITE = { email: "", role: "viewer" as Role };

function newIdempotencyKey(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    // ambientes sem crypto.randomUUID caem no fallback
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export default function CompanyWizard({ open, onClose, onCreated, onOpenCompany }: Props) {
  const [step, setStep] = useState(0);
  const [company, setCompany] = useState(EMPTY_COMPANY);
  const [inviteAnother, setInviteAnother] = useState(false);
  const [invite, setInvite] = useState(EMPTY_INVITE);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [inviteWarning, setInviteWarning] = useState("");
  const [responsibleHasAccount, setResponsibleHasAccount] = useState(false);
  const [created, setCreated] = useState<PlatformCompany | null>(null);
  const isCreating = useRef(false);
  // Chave de idempotência da tentativa atual: reenviada em cada retry para o
  // backend nunca criar uma 2ª empresa. Zerada ao começar uma empresa nova.
  const idempotencyKey = useRef("");

  function reset() {
    setStep(0);
    setCompany(EMPTY_COMPANY);
    setInviteAnother(false);
    setInvite(EMPTY_INVITE);
    setError("");
    setInviteWarning("");
    setResponsibleHasAccount(false);
    setCreated(null);
    idempotencyKey.current = "";
  }

  function handleClose() {
    if (saving) return;
    reset();
    onClose();
  }

  const canAdvanceFromDados = company.name.trim().length >= 2 && company.responsible_email.trim().includes("@");

  async function handleCreate() {
    if (isCreating.current) return;
    isCreating.current = true;
    if (!idempotencyKey.current) idempotencyKey.current = newIdempotencyKey();
    setSaving(true);
    setError("");
    setInviteWarning("");
    try {
      const response = await createPlatformCompany({
        name: company.name.trim(),
        trade_name: company.trade_name.trim() || undefined,
        cnpj: company.cnpj.trim() || undefined,
        responsible_email: company.responsible_email.trim(),
        idempotency_key: idempotencyKey.current,
      });
      setResponsibleHasAccount(Boolean(response.responsible_account_exists));
      if (inviteAnother && invite.email.trim()) {
        try {
          await createClientInvitation({
            client_id: response.company.id,
            email: invite.email.trim(),
            role: invite.role,
          });
        } catch (inviteCause) {
          setInviteWarning(
            inviteCause instanceof Error
              ? `Empresa criada, mas o convite adicional falhou: ${inviteCause.message}`
              : "Empresa criada, mas o convite adicional falhou."
          );
        }
      }
      setCreated(response.company);
      setStep(4);
      onCreated(response.company);
    } catch (cause) {
      // Em erro, os dados preenchidos permanecem para o usuário corrigir sem redigitar.
      setError(cause instanceof Error ? cause.message : "Não foi possível criar a empresa.");
    } finally {
      isCreating.current = false;
      setSaving(false);
    }
  }

  return (
    <Drawer
      open={open}
      title="Nova empresa"
      description={`Passo ${Math.min(step + 1, STEPS.length)} de ${STEPS.length} · ${STEPS[step]}`}
      onClose={handleClose}
      width="lg"
      footer={
        <>
          {step > 0 && step < 4 ? (
            <button type="button" className="btn" disabled={saving} onClick={() => setStep((s) => s - 1)}>
              Voltar
            </button>
          ) : null}
          {step === 0 ? (
            <button type="button" className="btn btnPrimary" disabled={!canAdvanceFromDados} onClick={() => setStep(1)}>
              Continuar
            </button>
          ) : null}
          {step === 1 ? (
            <button type="button" className="btn btnPrimary" onClick={() => setStep(2)}>
              Continuar
            </button>
          ) : null}
          {step === 2 ? (
            <button type="button" className="btn btnPrimary" onClick={() => setStep(3)}>
              Continuar
            </button>
          ) : null}
          {step === 3 ? (
            <button type="button" className="btn btnPrimary" disabled={saving} onClick={() => void handleCreate()}>
              {saving ? "Criando empresa..." : "Criar empresa"}
            </button>
          ) : null}
          {step === 4 ? (
            <button type="button" className="btn btnPrimary" onClick={handleClose}>
              Fechar
            </button>
          ) : null}
        </>
      }
    >
      <div className="wizardSteps" aria-hidden="true">
        {STEPS.map((label, index) => (
          <span key={label} className={`wizardStep${index === step ? " is-active" : ""}${index < step ? " is-done" : ""}`}>
            {label}
          </span>
        ))}
      </div>

      {step === 0 ? (
        <div className="wizardPane">
          <label>Razão social
            <input required minLength={2} value={company.name}
              onChange={(e) => setCompany({ ...company, name: e.target.value })} autoFocus />
          </label>
          <label>Nome fantasia
            <input value={company.trade_name}
              onChange={(e) => setCompany({ ...company, trade_name: e.target.value })} />
          </label>
          <label>CNPJ (opcional)
            <input inputMode="numeric" value={company.cnpj}
              onChange={(e) => setCompany({ ...company, cnpj: e.target.value })} />
          </label>
          <label>E-mail do responsável
            <input required type="email" value={company.responsible_email}
              onChange={(e) => setCompany({ ...company, responsible_email: e.target.value })} />
          </label>
          <p className="wizardHint">O responsável recebe o primeiro convite de acesso automaticamente.</p>
        </div>
      ) : null}

      {step === 1 ? (
        <div className="wizardPane">
          <label className="wizardCheckboxRow">
            <input type="checkbox" checked={inviteAnother} onChange={(e) => setInviteAnother(e.target.checked)} />
            Convidar mais um usuário agora
          </label>
          {inviteAnother ? (
            <>
              <label>E-mail
                <input type="email" value={invite.email}
                  onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
              </label>
              <label>Papel
                <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value as Role })}>
                  <option value="viewer">Somente leitura</option>
                  <option value="client_admin">Administrador do cliente</option>
                  <option value="agency_admin">Administrador da agência</option>
                </select>
              </label>
              <p className="wizardHint">{ROLE_DESCRIPTIONS[invite.role]}</p>
            </>
          ) : (
            <p className="wizardHint">Você pode pular esta etapa e convidar pessoas depois, em Usuários.</p>
          )}
        </div>
      ) : null}

      {step === 2 ? (
        <div className="wizardPane">
          <p className="wizardHint">
            A empresa pode ser criada sem nenhuma integração conectada. Meta, Google e Shopify podem ser
            conectados a qualquer momento depois, na tela de Integrações da empresa.
          </p>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="wizardPane">
          <dl className="wizardReview">
            <div><dt>Razão social</dt><dd>{company.name || "—"}</dd></div>
            <div><dt>Nome fantasia</dt><dd>{company.trade_name || "—"}</dd></div>
            <div><dt>CNPJ</dt><dd>{company.cnpj || "—"}</dd></div>
            <div><dt>Responsável</dt><dd>{company.responsible_email || "—"}</dd></div>
            <div>
              <dt>Convite adicional</dt>
              <dd>{inviteAnother && invite.email ? `${invite.email} · ${ROLE_DESCRIPTIONS[invite.role]}` : "Nenhum"}</dd>
            </div>
          </dl>
          {error ? <p className="wizardError" role="alert">{error}</p> : null}
        </div>
      ) : null}

      {step === 4 ? (
        <div className="wizardPane wizardDone">
          <div className="wizardDoneCheck" aria-hidden="true">✓</div>
          <h3>Empresa criada</h3>
          <p>{created?.trade_name || created?.name} está pronta para receber integrações e usuários.</p>
          {responsibleHasAccount ? (
            <p className="wizardHint" role="status">
              O responsável já tem conta na Mugô, então o e-mail automático de convite não foi
              reenviado. Use “Gerar link de onboarding” na lista de empresas para ele confirmar
              o acesso a esta empresa.
            </p>
          ) : null}
          {inviteWarning ? <p className="wizardError" role="alert">{inviteWarning}</p> : null}
          <div className="wizardDoneActions">
            <button
              type="button"
              className="btn btnPrimary"
              onClick={() => {
                if (created) onOpenCompany(created);
                reset();
                onClose();
              }}
            >
              Abrir empresa
            </button>
            <button type="button" className="btn" onClick={() => { reset(); }}>
              Criar outro cliente
            </button>
          </div>
        </div>
      ) : null}
    </Drawer>
  );
}
