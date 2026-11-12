import { useCallback, useEffect, useState } from "react";
import { connectClarity, disconnectChannel, getChannels, startChannel, syncChannel, type Channel, type ChannelTotals } from "../../app/channels";
import { formatDateTimeSaoPaulo } from "../../app/dataFormat";
import "../../styles/channels.css";

const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const int = (v: number | string | null | undefined) => (v == null || v === "" ? "—" : Number(v).toLocaleString("pt-BR"));
const STATUS: Record<string, [string, string]> = {
  connected: ["Conectado", "ok"], not_connected: ["Não conectado", "off"], reauth_required: ["Reconectar", "bad"],
  sync_error: ["Erro na coleta", "bad"], token_expired: ["Reconectar", "bad"],
};

function Numbers({ provider, m }: { provider: string; m: ChannelTotals }) {
  if (provider === "tiktok") {
    return <p className="chNums">{int(m.latest?.followers)} seguidores · {int(m.latest?.likes)} curtidas
      {m.top[0] ? <> · vídeo mais visto: {m.top[0].name} ({int(m.top[0].value)})</> : null}</p>;
  }
  if (provider === "clarity") {
    return <p className="chNums">{int(m.latest?.totalSessionCount)} sessões ontem
      {m.latest?.["RageClickCount.sessionsWithMetricPercentage"] != null ? <> · {String(m.latest["RageClickCount.sessionsWithMetricPercentage"])}% com clique de raiva</> : null}
      {m.top[0] ? <> · página com mais sessões: {m.top[0].name}</> : null}</p>;
  }
  if (provider === "pinterest") {
    return <p className="chNums">Orgânico: {int(m.impressions)} impressões · {int(m.clicks)} cliques para o site</p>;
  }
  if (provider === "linkedin") {
    return <p className="chNums">Página: {int(m.latest?.followers)} seguidores · {int(m.impressions)} impressões · {int(m.clicks)} cliques</p>;
  }
  const label = provider === "pinterest_ads" || provider === "linkedin_ads" ? "Anúncios" : "7 dias";
  return <p className="chNums">{label}: {brl(m.spend)} investidos · {int(m.impressions)} impressões · {int(m.clicks)} cliques · {int(m.conversions)} conversões</p>;
}

/** TikTok Ads, TikTok orgânico, Pinterest e Clarity: ligar, ver se está coletando e os números da semana. */
export default function ChannelsPanel({ canManage }: { canManage: boolean }) {
  const [rows, setRows] = useState<Channel[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clarityOpen, setClarityOpen] = useState(false);
  const [token, setToken] = useState("");
  const [project, setProject] = useState("");

  const load = useCallback(async () => {
    try { setRows((await getChannels()).channels); setError(null); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível ler os canais."); }
  }, []);
  useEffect(() => {
    void load();
    const params = new URLSearchParams(window.location.search);
    if (params.get("channel_oauth") === "success") setNotice("Conta conectada. A primeira coleta já começou.");
    if (params.get("channel_oauth") === "error") setError(params.get("error") || "A conexão não foi concluída.");
  }, [load]);

  const run = async (key: string, task: () => Promise<void>) => {
    setBusy(key); setError(null); setNotice(null);
    try { await task(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Não deu certo agora."); }
    finally { setBusy(null); }
  };

  return <section className="chPanel" aria-label="Novos canais">
    <header><h2>TikTok, Pinterest, LinkedIn e Clarity</h2>
      <p>Cada marca liga a própria conta. Os dados entram no MUGOVERSO sozinhos e reconectar nunca apaga o histórico.</p></header>
    {notice ? <p className="chNotice" role="status">{notice}</p> : null}
    {error ? <p className="chError" role="alert">{error}</p> : null}
    {!rows ? <p className="chMuted">Carregando canais…</p> : <ul>
      {rows.map((c) => {
        const [label, tone] = STATUS[c.status] || [c.status, "off"];
        const connected = c.status !== "not_connected";
        const metrics = Object.entries(c.metrics || {});
        return <li key={c.provider} className="chRow">
          <div className="chHead">
            <span className={`chDot is-${tone}`} aria-hidden="true" />
            <div className="chName"><b>{c.label}</b>{c.account_name ? <small>{c.account_name}</small> : null}</div>
            <span className={`chStatus is-${tone}`}>{label}</span>
            {canManage ? <div className="chActions">
              {(!connected || tone === "bad") && c.auth === "oauth" ? <button type="button" className="btn btnPrimary" disabled={!!busy || !c.app_configured}
                title={c.app_configured ? undefined : "O app desta plataforma ainda não foi configurado no servidor."}
                onClick={() => void run(c.provider, async () => { window.location.assign((await startChannel(c.provider)).authorization_url); })}>
                {connected ? "Reconectar" : "Conectar"}</button> : null}
              {(!connected || tone === "bad") && c.auth === "token" ? <button type="button" className="btn btnPrimary" disabled={!!busy}
                onClick={() => setClarityOpen((v) => !v)}>{connected ? "Trocar token" : "Conectar"}</button> : null}
              {connected ? <button type="button" className="btn btnGhost" disabled={!!busy} onClick={() => void run(c.provider, async () => {
                const out = await syncChannel(c.provider);
                setNotice(out.status === "ok" ? `${c.label}: ${out.rows} registros atualizados.` : out.status === "recent" ? `${c.label} já foi atualizado há pouco.` : out.message || "Coleta com erro.");
                await load();
              })}>{busy === c.provider ? "Atualizando…" : "Atualizar"}</button> : null}
              {connected ? <button type="button" className="btn btnGhost" disabled={!!busy} onClick={() => void run(c.provider, async () => {
                if (!window.confirm(`Desconectar ${c.label}? O histórico fica guardado.`)) return;
                await disconnectChannel(c.provider); await load();
              })}>Desconectar</button> : null}
            </div> : null}
          </div>
          {!c.app_configured && !connected ? <p className="chMuted">Aguardando o app da plataforma ser aprovado e configurado no servidor.</p> : null}
          {c.last_error && tone === "bad" ? <p className="chError">{c.last_error}</p> : null}
          {metrics.map(([key, m]) => m ? <Numbers key={key} provider={key} m={m} /> : null)}
          {connected && c.last_sync_at ? <p className="chMuted">Última coleta: {formatDateTimeSaoPaulo(c.last_sync_at)}</p> : null}
          {c.provider === "clarity" && clarityOpen && canManage ? <form className="chForm" onSubmit={(e) => { e.preventDefault(); void run("clarity", async () => {
            const out = await connectClarity(token.trim(), project.trim());
            setNotice(`Clarity conectado: ${out.rows} registros do último dia.`); setToken(""); setClarityOpen(false); await load();
          }); }}>
            <label>Token de exportação do projeto<input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" required minLength={20} /></label>
            <label>Nome do projeto (opcional)<input type="text" value={project} onChange={(e) => setProject(e.target.value)} maxLength={120} /></label>
            <small>No Clarity: Configurações → Exportação de dados → Gerar novo token.</small>
            <button type="submit" className="btn btnPrimary" disabled={busy === "clarity"}>{busy === "clarity" ? "Validando…" : "Salvar e coletar"}</button>
          </form> : null}
        </li>;
      })}
    </ul>}
  </section>;
}
