import { useEffect, useState } from "react";
import { ApiError, getAiSettings, revokeAiCredential, saveAiSettings, type AiModelOption, type AiSettings } from "../app/api";
import { getActiveClientId } from "../app/activeClient";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Não foi possível salvar a configuração de IA.";
}

export default function AiSettingsPanel() {
  const clientId = getActiveClientId();
  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [models, setModels] = useState<AiModelOption[]>([]);
  const [mode, setMode] = useState<AiSettings["mode"]>("platform_managed");
  const [model, setModel] = useState("gpt-4.1-mini");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setSettings(null); setError(""); setNotice(""); setKey("");
    getAiSettings().then((out) => {
      if (!active || out.settings.client_id !== getActiveClientId()) return;
      setSettings(out.settings); setModels(out.models); setMode(out.settings.mode); setModel(out.settings.model);
    }).catch((cause) => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [clientId]);

  async function save() {
    setBusy(true); setError(""); setNotice("");
    try {
      const out = await saveAiSettings({ mode, model, ...(key.trim() ? { api_key: key.trim() } : {}) });
      if (out.settings.client_id !== getActiveClientId()) return;
      setSettings(out.settings); setKey(""); setNotice("Configuração de IA salva.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function revoke() {
    setBusy(true); setError(""); setNotice("");
    try {
      const out = await revokeAiCredential();
      if (out.settings.client_id !== getActiveClientId()) return;
      setSettings(out.settings); setMode(out.settings.mode); setKey("");
      setNotice("Chave removida. A IA voltou ao modo gerenciado pela Mugô.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  return <section className="card cardWide" aria-labelledby="ai-settings-title">
    <div className="sectionHeader"><div>
      <h2 id="ai-settings-title" className="integrationsSectionTitle">Inteligência artificial</h2>
      <div className="p">Escolha entre a IA gerenciada pela Mugô e uma chave OpenAI exclusiva desta empresa.</div>
    </div></div>
    {!settings ? <p className="smallMuted">Carregando configuração…</p> : <div className="onboardingFormGrid">
      <label>Modo de IA<select value={mode} onChange={(event) => setMode(event.target.value as AiSettings["mode"])} disabled={busy}>
        <option value="platform_managed">Gerenciada pela Mugô</option><option value="byok">Chave própria (BYOK)</option>
      </select></label>
      <label>Modelo<select value={model} onChange={(event) => setModel(event.target.value)} disabled={busy}>
        {models.map((item) => <option key={item.model} value={item.model}>{item.model}</option>)}
      </select></label>
      {mode === "byok" ? <label>Chave OpenAI<input type="password" autoComplete="new-password" value={key}
        onChange={(event) => setKey(event.target.value)}
        placeholder={settings.has_credential ? "Chave configurada — deixe vazio para manter" : "Cole a chave desta empresa"} disabled={busy} />
        <span className="smallMuted">A chave é criptografada no servidor e nunca volta para o navegador.</span></label> : null}
      <div className="onboardingHeroActions">
        <button className="btn btnPrimary" type="button" disabled={busy || (mode === "byok" && !settings.has_credential && !key.trim())} onClick={() => void save()}>{busy ? "Validando…" : "Salvar configuração"}</button>
        {settings.has_credential ? <button className="btn btnGhost" type="button" disabled={busy} onClick={() => void revoke()}>Revogar chave</button> : null}
      </div>
      <p className="smallMuted">Estado: {settings.mode === "platform_managed" ? "IA da Mugô" : settings.credential_status === "valid" ? "chave própria validada" : "chave pendente"}.</p>
    </div>}
    {notice ? <p role="status" className="smallMuted">{notice}</p> : null}
    {error ? <p role="alert" className="errorBox">{error}</p> : null}
  </section>;
}
