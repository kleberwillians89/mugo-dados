import { useDataHealth } from "../../app/DataHealthContext";
import { HEALTH_LABELS, SOURCE_LABELS } from "../../app/dataHealth";
import { formatFreshness } from "../../app/dataRefresh";

const reason: Record<string, string> = {
  SYNC_FAILED: "última tentativa falhou; dados anteriores mantidos",
  INCOMPLETE_COLLECTION: "coleta parcial; dados anteriores mantidos",
  FRESHNESS_READ_FAILED: "não foi possível confirmar o estado da fonte",
  CONNECTION_AMBIGUOUS: "mais de uma conexão; fonte em uso não confirmada",
  OPERATION_NOT_CONFIRMED_RUNNING: "não foi possível confirmar se a atualização continua em andamento",
};
const day = (value: string) => value.length > 10
  ? new Date(value).toLocaleDateString("pt-BR", {timeZone: "America/Sao_Paulo"})
  : value.slice(0, 10).split("-").reverse().join("/");
export function DataFreshness({ provider, compact = false }: {provider: string; compact?: boolean}) {
  const health = useDataHealth();
  const source = health?.data?.sources.find(item => item.provider === provider);
  if (compact) {
    const format = (value: string | null | undefined) => {
      const at = value ? new Date(value) : null;
      if (!at || Number.isNaN(at.getTime())) return null;
      const parts = new Intl.DateTimeFormat("pt-BR", {timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", hourCycle: "h23"}).formatToParts(at);
      const part = (name: string) => parts.find(item => item.type === name)?.value;
      return `${part("day")}/${part("month")}/${part("year")} às ${part("hour")}`;
    };
    if (source?.state === "reauth_required") return <span>Reconexão necessária · dados anteriores mantidos</span>;
    // Coleta parcial também grava dados novos (o que faltou manteve o valor anterior).
    const updated = format(source?.last_successful_sync_at) || format(source?.last_updated_at);
    const failedAttempt = source?.sync_status === "error" ? format(source?.last_attempt_at) : null;
    if (updated) return <span>Atualizado em {updated}{failedAttempt && failedAttempt !== updated ? ` · nova tentativa em ${failedAttempt} falhou` : ""}</span>;
    // A plataforma respondeu, mas sem nada no período (ex.: conta Meta sem anúncio
    // rodando). Não é falha: mostra quando foi consultada.
    const checked = source?.sync_status === "no_data" ? format(source?.last_attempt_at) : null;
    if (checked) return <span>Consultado em {checked} · {provider === "meta_ads" ? "sem anúncios no período" : "sem dados no período"}</span>;
    if (failedAttempt) return <span>Última tentativa em {failedAttempt} falhou · nova tentativa automática</span>;
    return <span>Ainda não atualizado</span>;
  }
  if (!source) return <span>{health?.loading ? "Verificando situação dos dados…" : "Situação dos dados não confirmada"}</span>;
  return <span>
    {health?.error ? "Leitura de status indisponível · última evidência: " : ""}{HEALTH_LABELS[source.state]}
    {source.last_successful_sync_at ? ` · Última sincronização da fonte ${formatFreshness(source.last_successful_sync_at)}` : " · sem sucesso confirmado"}
    {source.last_attempt_at && ["error", "partial", "running"].includes(source.sync_status) ? ` · Última tentativa ${formatFreshness(source.last_attempt_at)}` : ""}
    {source.error_code && reason[source.error_code] ? ` · ${reason[source.error_code]}` : ""}
    {source.last_data_at ? ` · ${source.last_data_semantics === "latest_publication_timestamp_in_period" ? "Publicação mais recente" : "Dados registrados até"} ${day(source.last_data_at)}` : ""}
    {source.coverage_end ? ` · Cobertura verificada até ${day(source.coverage_end)}` : " · cobertura não comprovada"}
    {source.state === "updating" ? " · mantendo os dados anteriores" : ""}
    {source.error_code === "FBITS_OFFICIAL_SNAPSHOT_MISSING" ? " · indicadores oficiais ainda não coletados para este período" : ""}
    {source.state === "attention" && !source.error_code ? " · cobertura completa do período não comprovada" : ""}
  </span>;
}

/** Friendly operation feedback; partial is derived only from persisted evidence. */
export function ProviderRefreshNotice({provider, control}: {provider: "meta" | "google" | "shopify" | "fbits"; control: {phase: string; message: string; outcome?: "success" | "failed"}}) {
  const health = useDataHealth();
  const providers = {meta: ["meta_ads", "instagram", "instagram_content"], google: ["ga4", "google_ads"], shopify: ["shopify"], fbits: ["fbits", "fbits_official"]}[provider];
  const partial = !health?.loading && control.outcome !== "success" && !["checking", "running"].includes(control.phase)
    && health?.data?.sources.some(source => providers.includes(source.provider) && source.sync_status === "partial");
  const message = partial ? "Algumas plataformas não puderam ser atualizadas na última coleta registrada. A leitura anterior continua disponível." : control.message;
  const state = partial ? "partial" : control.phase === "ready" && control.outcome ? control.outcome : control.phase;
  return message ? <p role="status" className="ds-status" data-refresh-state={state}>{message}</p> : null;
}

export function DataHealthSummary({onReconnect}: {onReconnect?: () => void}) {
  const health = useDataHealth();
  if (!health) return null;
  const sources = health.data?.sources.filter(source => source.connected || source.last_successful_sync_at || source.last_data_at || source.state === "attention") || [];
  return <details className="ds-caption" style={{margin: "12px 24px"}}>
    <summary>Saúde dos dados{health.error ? " · leitura indisponível" : health.loading ? " · verificando" : ""}</summary>
    <button type="button" onClick={() => void health.reload()} disabled={health.loading}>Consultar status persistido</button>
    <p>Sincronização e cobertura são evidências diferentes. Agendamentos automáticos ainda exigem confirmação operacional.</p>
    {!sources.length ? <p>Disponibilidade das fontes não confirmada.</p> : <ul>{sources.map(source => <li key={source.provider}><strong>{SOURCE_LABELS[source.provider] || source.provider}: </strong><DataFreshness provider={source.provider} />{source.state === "reauth_required" && onReconnect ? <> <button type="button" onClick={onReconnect}>Reconectar</button></> : null}</li>)}</ul>}
  </details>;
}
