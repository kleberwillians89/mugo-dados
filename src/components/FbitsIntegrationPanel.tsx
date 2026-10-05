import { useState, type FormEvent } from "react";
import { connectFbits, disconnectFbitsConnection, refreshProviderData } from "../app/api";
import type { ClientIntegrationConnection } from "../app/types";
import Drawer from "./Drawer";
import { getActiveClientId } from "../app/activeClient";
import { runExclusiveSync } from "../app/syncOrchestrator";
import { ensureDashboardPeriod } from "../hooks/dashboard/period";

type Props = {
  entry: ClientIntegrationConnection | undefined;
  canManage: boolean;
  onChanged: () => void | Promise<void>;
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Conexão FBITS por empresa. O token só existe no estado local enquanto o
 * drawer está aberto; é apagado logo após o envio (sucesso ou erro) e nunca
 * é exibido de novo — o backend também nunca o devolve.
 */
export default function FbitsIntegrationPanel({ entry, canManage, onChanged }: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const connected = Boolean(entry) && entry?.status !== "disconnected";

  function closeDrawer() {
    if (busy) return;
    setToken("");
    setError(null);
    setDrawerOpen(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = token.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      await connectFbits(value);
      setDrawerOpen(false);
      setInfo("FBITS conectada. A importação dos últimos 90 dias começou em segundo plano.");
      await onChanged();
    } catch (cause) {
      setError(errorText(cause, "Não foi possível validar o token da FBITS."));
    } finally {
      setToken("");
      setBusy(false);
    }
  }

  async function syncNow() {
    if (busy) return;
    const clientId = getActiveClientId();
    setBusy(true);
    setError(null);
    try {
      await runExclusiveSync({ clientId, provider: "fbits" }, () => refreshProviderData("fbits", ensureDashboardPeriod(undefined)));
      if (getActiveClientId() !== clientId) return;
      setInfo("Sincronização concluída.");
      await onChanged();
    } catch (cause) {
      setError(errorText(cause, "Não foi possível iniciar a sincronização."));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await disconnectFbitsConnection();
      setInfo("FBITS desconectada. Os dados já importados foram preservados.");
      await onChanged();
    } catch (cause) {
      setError(errorText(cause, "Não foi possível desconectar a FBITS."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="onboardingConnActions" style={{ marginTop: 10 }} data-testid="fbits-panel">
      {connected ? (
        <>
          <button className="btn btnGhost" type="button" disabled={!canManage || busy} onClick={() => void syncNow()}>
            {busy ? "Aguarde..." : "Sincronizar agora"}
          </button>
          <button className="btn btnGhost" type="button" disabled={!canManage || busy} onClick={() => setDrawerOpen(true)}>
            Atualizar token
          </button>
          <button className="btn btnGhost" type="button" disabled={!canManage || busy} onClick={() => void disconnect()}>
            Desconectar
          </button>
        </>
      ) : (
        <button className="btn btnGhost" type="button" disabled={!canManage || busy} onClick={() => setDrawerOpen(true)}>
          Conectar FBITS
        </button>
      )}
      {info ? <div className="smallMuted" role="status">{info}</div> : null}
      {error && !drawerOpen ? <div className="integrationErrorNotice" role="alert"><p>{error}</p></div> : null}

      <Drawer
        open={drawerOpen}
        title="Conectar FBITS"
        description="Token da API gerado no painel da loja (Configurações › Integrações › Tokens)."
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="btn" disabled={busy} onClick={closeDrawer}>Cancelar</button>
            <button type="submit" form="fbits-connect-form" className="btn btnPrimary" disabled={busy || !token.trim()}>
              {busy ? "Validando..." : "Validar e conectar"}
            </button>
          </>
        }
      >
        <form id="fbits-connect-form" className="wizardPane" onSubmit={(event) => void submit(event)}>
          <label>Token da API
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(event) => setToken(event.target.value)}
              autoFocus
            />
          </label>
          <p className="wizardHint">
            O token é validado na FBITS, salvo criptografado e nunca é exibido novamente.
          </p>
          {error ? <p className="wizardError" role="alert">{error}</p> : null}
        </form>
      </Drawer>
    </div>
  );
}
