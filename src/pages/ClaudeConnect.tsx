import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { http, setApiAccessToken } from "../app/api";
import { supabase } from "../app/supabase";
import Login from "./Login";

const NOTICE = "O Claude só lê dados agregados das empresas que você já acessa. Nenhum dado pessoal de comprador é compartilhado.";
type Connection = { id: string; name: string; created_at: string; last_used_at: string | null };
type Overview = { url: string; application?: string; companies: { id: string; name: string }[]; connections: Connection[] };

export function ClaudeConnectContent({ consent = false }: { consent?: boolean }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const query = window.location.search;

  useEffect(() => {
    const controller = new AbortController();
    http<Overview>(consent ? `/api/mcp/authorization${query}` : "/api/mcp/connections", { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch(() => { if (!controller.signal.aborted) setError("Não foi possível carregar o conector. Verifique sua sessão ou tente mais tarde."); });
    return () => controller.abort();
  }, [consent, query]);

  async function decide(approve: boolean) {
    if (busy || !data) return;
    setBusy(true); setError("");
    try {
      const params = Object.fromEntries(new URLSearchParams(query));
      const result = await http<{ redirect_url: string }>("/api/mcp/consent", { method: "POST", body: JSON.stringify({ ...params, approve }) });
      // O backend valida o callback exato contra registro e allowlist.
      window.location.assign(result.redirect_url);
    } catch {
      setError("Não foi possível concluir a autorização. Tente novamente.");
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await http("/api/mcp/connections/revoke", { method: "POST", body: JSON.stringify({ id }) });
      setData((value) => value && { ...value, connections: value.connections.filter((connection) => connection.id !== id) });
    } catch { setError("Não foi possível revogar a conexão. Tente novamente."); }
    finally { setBusy(false); }
  }

  return <main className="ds-page" style={{ maxWidth: 800, margin: "0 auto", padding: "clamp(16px, 4vw, 40px)", overflowWrap: "anywhere" }}>
    <a className="ds-button" href="/">Voltar ao Mugô Dados</a>
    <h1>{consent ? "Autorizar leitura pelo Claude" : "Conectar ao Claude"}</h1>
    <p>{NOTICE}</p>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">Carregando conexão segura...</p>}
    {data && <>
      {consent ? <>
        <h2>Aplicativo: {data.application}</h2>
        <p>Você autoriza a leitura das empresas às quais sua conta tem acesso. O acesso é conferido novamente a cada consulta.</p>
        <h3>Empresas disponíveis</h3>
        {data.companies.length ? <ul>{data.companies.map((company) => <li key={company.id}>{company.name}</li>)}</ul> : <p>Nenhuma empresa disponível no momento.</p>}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <button className="ds-button is-primary" disabled={busy} onClick={() => void decide(true)}>{busy ? "Processando..." : "Autorizar"}</button>
          <button className="ds-button" disabled={busy} onClick={() => void decide(false)}>Cancelar</button>
        </div>
      </> : <>
        <h2>URL do conector</h2><p><code>{data.url}</code></p>
        <button className="ds-button" onClick={() => void navigator.clipboard.writeText(data.url).then(() => setCopied(true)).catch(() => setError("Copie a URL exibida acima manualmente."))}>{copied ? "URL copiada" : "Copiar URL"}</button>
        <ol><li>No Claude, abra Configurações → Conectores.</li><li>Adicione um conector personalizado com a URL acima.</li><li>Entre com sua conta Mugô Dados e revise a autorização.</li></ol>
        <h2>Conexões ativas</h2>
        {data.connections.length ? <ul>{data.connections.map((connection) => <li key={connection.id} style={{ marginBottom: 16 }}>
          <strong>{connection.name}</strong><p>Criada em {new Date(connection.created_at).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" })}. Último uso: {connection.last_used_at ? new Date(connection.last_used_at).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" }) : "ainda não utilizada"}.</p>
          <button className="ds-button" disabled={busy} onClick={() => void revoke(connection.id)}>Revogar</button>
        </li>)}</ul> : <p>Nenhuma conexão ativa.</p>}
      </>}
    </>}
  </main>;
}

export default function ClaudeConnect() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(Boolean(supabase));
  const [error, setError] = useState("");
  useEffect(() => {
    if (!supabase) return;
    let alive = true;
    let authChanged = false;
    const apply = (next: Session | null) => { if (alive) { setApiAccessToken(next?.access_token); setSession(next); setChecking(false); } };
    void supabase.auth.getSession().then(({ data }) => { if (!authChanged) apply(data.session); }).catch(() => { if (alive) { setChecking(false); setError("Não foi possível verificar sua sessão."); } });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => { authChanged = true; apply(next); });
    return () => { alive = false; data.subscription.unsubscribe(); };
  }, []);
  if (checking) return <p role="status">Verificando acesso...</p>;
  if (!session) return <Login initialError={error || undefined} onPasswordLoginSuccess={(next) => { setApiAccessToken(next?.access_token); setSession(next); }} />;
  return <ClaudeConnectContent key={session.user.id} consent={window.location.pathname === "/conectar-claude/autorizar"} />;
}
