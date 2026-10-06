import { readOnce } from "../hooks/dashboard/readOnce";
import PeriodSelector from "../components/data/PeriodSelector";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  askIntelligence,
  generateIntelligenceAnalysis,
  getIntelligenceContext,
  getIntelligenceHistory,
  getLatestIntelligenceAnalysis,
} from "../app/api";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import type {
  IntelligenceAction,
  IntelligenceAnalysisRecord,
  IntelligenceInsight,
  IntelligenceMessage,
  IntelligenceMetric,
  IntelligenceSnapshot,
} from "../app/intelligenceTypes";
import {
  buildTestIdeas,
  describeSources,
  selectMovements,
  selectOpportunities,
} from "../app/intelligencePriority";
import { usePeriod } from "../app/PeriodContext";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "../hooks/dashboard/cache";
import { cooldownFrom, cooldownHint, formatFreshness, hasFresherData } from "../app/dataRefresh";
import "../styles/intelligence.css";

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    paid_media: "Mídia paga", ga4: "Google Analytics", shopify: "Loja virtual",
    "shopify+paid_media": "Loja virtual e mídia paga", meta_ads: "Meta Ads",
    google_ads: "Google Ads", instagram: "Instagram", fbits: "FBITS",
  };
  return labels[source] || source.replaceAll("_", " ");
}

type Props = {
  onLogout: () => void | Promise<void>;
  /**
   * Administração do contexto estratégico (PUT /business-context exige papel
   * de gestão). Gerar análise NÃO depende disto: qualquer membro gera.
   */
  canEditBusinessContext?: boolean;
};

type CachedWorkspace = {
  snapshot: IntelligenceSnapshot | null;
  analysis: IntelligenceAnalysisRecord | null;
  history: IntelligenceAnalysisRecord[];
  providerConfigured: boolean | null;
  /** Última sincronização persistida das fontes. */
  refreshedAt?: string | null;
};

/**
 * Último estado válido da central, em sessionStorage.
 *
 * Era um Map em memória: sobrevivia a trocas de rota, mas morria a cada carga
 * de página, e aí a tela abria em skeleton mesmo havendo análise persistida.
 * O cache do dashboard já resolvia isso — aqui só reaproveitamos o mesmo
 * mecanismo.
 */
const workspaceCache = {
  get(key: string): CachedWorkspace | null {
    return readDashboardCache<CachedWorkspace>(buildDashboardCacheKey("intelligence-workspace", { clientId: key }));
  },
  set(key: string, value: CachedWorkspace): void {
    writeDashboardCache<CachedWorkspace>(
      buildDashboardCacheKey("intelligence-workspace", { clientId: key }),
      value,
      600_000,
    );
  },
};

const QUESTIONS = [
  "Como está meu desempenho este mês?",
  "O que mais merece minha atenção?",
  "Como estão minhas vendas?",
  "Minha mídia está eficiente?",
  "O que mudou em relação ao período anterior?",
  "Onde existe oportunidade de crescimento?",
];

const FOLLOW_UPS = ["Por que isso aconteceu?", "Compare com o mês anterior", "O que devo priorizar?"];

const CATEGORY_LABELS: Record<IntelligenceInsight["category"], string> = {
  opportunity: "Oportunidade",
  attention: "Ponto de atenção",
  risk: "Risco",
  positive: "Resultado positivo",
  anomaly: "Anomalia",
  data_quality: "Qualidade dos dados",
};

const PRIORITY_LABELS: Record<IntelligenceAction["priority"], string> = {
  now: "Fazer agora",
  week: "Fazer nesta semana",
  monitor: "Acompanhar",
  investigate: "Investigar",
};

type InsightGroup = "positive" | "risk" | "opportunity";

const INSIGHT_GROUPS: { id: InsightGroup; title: string; categories: IntelligenceInsight["category"][] }[] = [
  { id: "positive", title: "Avanços", categories: ["positive"] },
  { id: "risk", title: "Riscos", categories: ["risk", "attention", "anomaly", "data_quality"] },
  { id: "opportunity", title: "Oportunidades", categories: ["opportunity"] },
];

function formatDate(value?: string | null, includeTime = false) {
  if (!value) return "Não disponível";
  const parsed = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    ...(includeTime ? { timeStyle: "short" as const } : {}),
  }).format(parsed);
}

function formatMetric(metric: IntelligenceMetric) {
  if (metric.value == null) {
    const statusLabel: Partial<Record<IntelligenceMetric["status"], string>> = {
      unavailable: "Indisponível",
      disconnected: "Não conectado",
      partial: "Parcial",
      error: "Erro na consulta",
    };
    return statusLabel[metric.status] || "Sem dados";
  }
  let formatted: string;
  if (metric.format === "currency") {
    formatted = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(metric.value);
  } else if (metric.format === "percent") {
    formatted = `${metric.value.toLocaleString("pt-BR")}%`;
  } else if (metric.format === "decimal") {
    formatted = `${metric.value.toLocaleString("pt-BR")}x`;
  } else {
    formatted = Math.round(metric.value).toLocaleString("pt-BR");
  }
  return metric.status === "partial" ? `${formatted} · parcial` : formatted;
}

function metricMap(metrics: IntelligenceMetric[]) {
  return new Map(metrics.map((metric) => [metric.id, metric]));
}


function IntelligenceSkeleton() {
  return (
    <div className="intelSkeleton" aria-label="Carregando inteligência" aria-busy="true">
      <div className="intelSkeletonHero" />
      <div className="intelSkeletonMetrics">{Array.from({ length: 5 }, (_, index) => <span key={index} />)}</div>
      <div className="intelSkeletonBody"><span /><span /></div>
    </div>
  );
}

function Evidence({
  ids,
  metrics,
}: {
  ids: string[];
  metrics: Map<string, IntelligenceMetric>;
}) {
  const items = ids.map((id) => metrics.get(id)).filter(Boolean) as IntelligenceMetric[];
  if (!items.length) return <p className="intelMuted">Sem evidência numérica suficiente.</p>;
  return (
    <div className="intelEvidence">
      {items.map((metric) => (
        <span key={metric.id}>
          <small>{metric.label}</small>
          <strong>{formatMetric(metric)}</strong>
          {metric.variation_percent != null ? <small>{metric.variation_percent > 0 ? "+" : ""}{metric.variation_percent.toLocaleString("pt-BR")}% vs. período anterior</small> : null}
        </span>
      ))}
    </div>
  );
}

// onLogout segue no tipo por compatibilidade: a saída vive na sidebar global.
export default function Intelligence({ canEditBusinessContext = false }: Props) {
  const { period } = usePeriod();
  const clientId = getActiveClientId();
  const cacheKey = `${clientId}:${period.start}:${period.end}`;
  const cached = workspaceCache.get(cacheKey);
  const [snapshot, setSnapshot] = useState<IntelligenceSnapshot | null>(cached?.snapshot || null);
  const [analysis, setAnalysis] = useState<IntelligenceAnalysisRecord | null>(cached?.analysis || null);
  const [history, setHistory] = useState<IntelligenceAnalysisRecord[]>(cached?.history || []);
  const [providerConfigured, setProviderConfigured] = useState<boolean | null>(
    cached?.providerConfigured ?? null,
  );
  const [loading, setLoading] = useState(!cached);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<IntelligenceMessage[]>([]);
  // "Atualizar dados" relê o que já está persistido. Não é geração de IA e
  // não sincroniza provider: o custo é o de três GETs que o usuário já pode
  // fazer. Por isso vale para viewer também.
  const [revalidating, setRevalidating] = useState(false);
  const [lastRefreshAt, setLastRefreshAt] = useState<number | null>(null);
  const [, setRefreshedAt] = useState<string | null>(cached?.refreshedAt || null);
  // Só move os rótulos relativos e libera o cooldown. Nenhuma requisição.
  const [refreshTick, setRefreshTick] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setRefreshTick(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);
  const generatingRef = useRef(false);
  const requestVersion = useRef(0);
  const refreshController = useRef<AbortController | null>(null);
  const askController = useRef<AbortController | null>(null);
  const questionInput = useRef<HTMLTextAreaElement | null>(null);
  const questionForm = useRef<HTMLFormElement | null>(null);
  const conversationView = useRef<HTMLDivElement | null>(null);
  const workspaceView = useRef<HTMLDivElement | null>(null);
  const retryKind = useRef<"read" | "analysis" | "question">("read");
  const cacheKeyRef = useRef(cacheKey);

  useEffect(() => {
    if (messages.length) conversationView.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [messages.length]);

  function chooseQuestion(value: string) {
    setQuestion(value);
    questionInput.current?.focus();
  }

  // Troca de empresa (ou período) nunca pode deixar o snapshot/análise/
  // histórico do tenant anterior visível — nem por um frame, e nem
  // indefinidamente quando o novo tenant ainda não tem nada em cache
  // (antes, esse caso não limpava snapshot/analysis/history, só ligava o
  // loading). Reset síncrono durante o render, não em useEffect.
  if (cacheKeyRef.current !== cacheKey) {
    cacheKeyRef.current = cacheKey;
    requestVersion.current += 1;
    refreshController.current?.abort();
    askController.current?.abort();
    const nextCache = workspaceCache.get(cacheKey);
    setSnapshot(nextCache?.snapshot || null);
    setAnalysis(nextCache?.analysis || null);
    setHistory(nextCache?.history || []);
    setProviderConfigured(nextCache?.providerConfigured ?? null);
    setRefreshedAt(nextCache?.refreshedAt || null);
    setLoading(!nextCache);
    setError("");
    setConversationId(null);
    setMessages([]);
  }

  // Leitura do workspace: a mesma para a abertura da tela e para o botão
  // "Atualizar dados". Só GETs já autorizados — nenhuma mutação, nenhuma IA.
  const loadWorkspace = useCallback((controller: AbortController) => {
    const version = ++requestVersion.current;
    const currentCache = workspaceCache.get(cacheKey);
    setError("");
    const live = () => !controller.signal.aborted && version === requestVersion.current;
    const persist = (patch: Partial<CachedWorkspace>) => {
      if (!live()) return;
      workspaceCache.set(cacheKey, { snapshot: null, analysis: null, history: [], providerConfigured: null,
        ...currentCache, ...workspaceCache.get(cacheKey), ...patch });
    };
    return Promise.allSettled([
      readOnce(`intelligence-context:${cacheKey}`, () => getIntelligenceContext(period)).then(result => {
        if (live()) { setSnapshot(result.snapshot); setLoading(false); persist({ snapshot: result.snapshot }); }
        return result;
      }),
      readOnce(`intelligence-latest:${cacheKey}`, () => getLatestIntelligenceAnalysis(period)).then(result => {
        if (live()) { setAnalysis(result.analysis); setProviderConfigured(result.provider_configured);
          if (result.analysis) setLoading(false);
          persist({ analysis: result.analysis, providerConfigured: result.provider_configured }); }
        return result;
      }),
      readOnce(`intelligence-history:${clientId}:20`, () => getIntelligenceHistory(20)).then(result => {
        if (live()) { setHistory(result.items); persist({ history: result.items }); }
        return result;
      }),
    ]).then(([contextResult, latestResult, historyResult]) => {
      if (controller.signal.aborted || version !== requestVersion.current) return;
      const nextSnapshot =
        contextResult.status === "fulfilled" ? contextResult.value.snapshot : currentCache?.snapshot || null;
      const nextAnalysis =
        latestResult.status === "fulfilled" ? latestResult.value.analysis : currentCache?.analysis || null;
      const nextHistory =
        historyResult.status === "fulfilled" ? historyResult.value.items : currentCache?.history || [];
      const nextProvider =
        latestResult.status === "fulfilled"
          ? latestResult.value.provider_configured
          : currentCache?.providerConfigured ?? null;
      setSnapshot(nextSnapshot);
      setAnalysis(nextAnalysis);
      setHistory(nextHistory);
      setProviderConfigured(nextProvider);
      const nextRefreshedAt = nextSnapshot?.last_sync_at || null;
      setRefreshedAt(nextRefreshedAt);
      workspaceCache.set(cacheKey, {
        snapshot: nextSnapshot,
        analysis: nextAnalysis,
        history: nextHistory,
        providerConfigured: nextProvider,
        refreshedAt: nextRefreshedAt,
      });
      const failed = [contextResult, latestResult, historyResult].filter((item) => item.status === "rejected");
      if (failed.length === 3) {
        retryKind.current = "read";
        const reason = failed[0].status === "rejected" ? failed[0].reason : null;
        setError(reason instanceof Error ? reason.message : "Não foi possível carregar a central de inteligência.");
      }
      setLoading(false);
    });
  }, [cacheKey, clientId, period]);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void loadWorkspace(controller); });
    return () => {
      cancelled = true;
      controller.abort();
      refreshController.current?.abort();
      askController.current?.abort();
    };
  }, [loadWorkspace]);

  /**
   * "Atualizar dados": revalida o que está persistido.
   *
   * Não chama provider nem OpenAI — é exatamente a releitura que a abertura
   * da tela faz. Por isso vale para qualquer membro, viewer incluído, sem
   * ampliar privilégio nenhum.
   */
  const refreshData = useCallback(async () => {
    if (!cooldownFrom(lastRefreshAt).ready || revalidating) return;
    setLastRefreshAt(Date.now());
    setRevalidating(true);
    const controller = new AbortController();
    try {
      await loadWorkspace(controller);
    } finally {
      setRevalidating(false);
    }
  }, [lastRefreshAt, loadWorkspace, revalidating]);

  const displayedMetrics = useMemo(
    () => analysis?.metrics_snapshot?.length
      ? analysis.metrics_snapshot
      : snapshot?.metrics || [],
    [analysis?.metrics_snapshot, snapshot?.metrics],
  );
  const metrics = useMemo(() => metricMap(displayedMetrics), [displayedMetrics]);
  const conversationMetrics = useMemo(() => metricMap(snapshot?.metrics || []), [snapshot?.metrics]);
  const content = analysis?.status === "completed" ? analysis.analysis : null;
  const commerceContext = snapshot?.commerce_context;
  const metricIndex = useMemo(() => metricMap(snapshot?.metrics || []), [snapshot?.metrics]);
  // Prioridade a partir dos sinais que já existem na análise: nenhum score
  // numérico inventado e nenhum texto novo gerado aqui.
  const movements = useMemo(
    () => selectMovements(content?.insights, metricIndex),
    [content?.insights, metricIndex]
  );
  const opportunities = useMemo(
    () => selectOpportunities(content?.insights, metricIndex, movements),
    [content?.insights, metricIndex, movements]
  );
  const testIdeas = useMemo(() => buildTestIdeas(content, metricIndex), [content, metricIndex]);
  const sourceNames = useMemo(() => describeSources(snapshot), [snapshot]);
  const businessContextAvailable = Boolean(snapshot?.business_context?.available);
  const refreshCooldown = cooldownFrom(lastRefreshAt, refreshTick);
  const dataFreshnessLabel = useMemo(
    () => formatFreshness(snapshot?.last_sync_at, refreshTick),
    [snapshot?.last_sync_at, refreshTick],
  );
  /** Integrações mais novas que a última análise: avisa, não gera nada. */
  const fresherDataAvailable = useMemo(
    () => hasFresherData(snapshot?.last_sync_at, analysis?.completed_at || analysis?.created_at),
    [snapshot?.last_sync_at, analysis?.completed_at, analysis?.created_at],
  );

  const analysisUpdatedLabel = useMemo(
    () => formatDate(analysis?.completed_at || analysis?.created_at, true),
    [analysis?.completed_at, analysis?.created_at]
  );
  // Cobertura de fontes em linguagem humana: "4 de 5 fontes com dados" é
  // verificável; "qualidade 80%" soa como nota e não explica nada.
  const sourceCoverage = snapshot?.quality
    ? `${snapshot.quality.available_sources} de ${snapshot.quality.total_sources} fontes com dados no período`
    : "";
  // Frescor pelo último SUCESSO das fontes (nunca por tentativa de sync).
  const updatedLabel = useMemo(
    () => (snapshot?.last_sync_at ? formatDate(snapshot.last_sync_at, true) : ""),
    [snapshot?.last_sync_at]
  );
  // Pesquisa externa só aparece com provider real E item verificável: sem
  // provider, nada de seção vazia nem dado inventado.
  const research = snapshot?.external_research;
  const researchAvailable = research?.status === "ok";
  const marketSignals = researchAvailable ? research?.market_signals || [] : [];
  const contentReferences = researchAvailable ? research?.content_references || [] : [];
  const ugcCreators = researchAvailable ? research?.ugc_creators || [] : [];

  async function refreshAnalysis() {
    // `refreshing` é estado: num clique duplo rápido o segundo handler ainda
    // enxerga `false` e dispara outra chamada ao provedor de IA. A guarda
    // precisa ser síncrona.
    if (generatingRef.current) return;
    generatingRef.current = true;
    setRefreshing(true);
    setError("");
    refreshController.current?.abort();
    const controller = new AbortController();
    refreshController.current = controller;
    try {
      const result = await generateIntelligenceAnalysis(period, { signal: controller.signal });
      // A resposta recém-gerada passa a ser autoritativa. Leituras iniciais
      // atrasadas não podem reintroduzir um erro antigo sobre essa versão.
      requestVersion.current += 1;
      setSnapshot(result.snapshot);
      setAnalysis(result.analysis);
      setProviderConfigured(result.provider_configured);
      setError("");
      const nextHistory = [result.analysis, ...history.filter((item) => item.id !== result.analysis.id)];
      setHistory(nextHistory);
      // Gerar análise não altera o horário de sincronização das fontes.
      const generatedAt = result.snapshot.last_sync_at || null;
      setRefreshedAt(generatedAt);
      workspaceCache.set(cacheKey, {
        snapshot: result.snapshot,
        analysis: result.analysis,
        history: nextHistory,
        providerConfigured: result.provider_configured,
        refreshedAt: generatedAt,
      });
    } catch (cause) {
      if (!controller.signal.aborted) {
        retryKind.current = "analysis";
        setError(cause instanceof Error ? cause.message : "Não foi possível atualizar a análise.");
      }
    } finally {
      generatingRef.current = false;
      if (refreshController.current === controller) setRefreshing(false);
    }
  }

  async function submitQuestion(event: FormEvent) {
    event.preventDefault();
    const clean = question.trim();
    if (!clean || asking) return;
    setAsking(true);
    setError("");
    askController.current?.abort();
    const controller = new AbortController();
    askController.current = controller;
    try {
      const result = await askIntelligence({
        question: clean,
        conversation_id: conversationId,
        start: period.start,
        end: period.end,
      }, { signal: controller.signal });
      setConversationId(result.conversation_id);
      setMessages((current) => [...current, result.user_message, result.assistant_message]);
      setSnapshot(result.snapshot);
      setQuestion("");
    } catch (cause) {
      if (!controller.signal.aborted) {
        retryKind.current = "question";
        setError(cause instanceof Error ? cause.message : "A pergunta não pôde ser respondida.");
      }
    } finally {
      if (askController.current === controller) setAsking(false);
    }
  }

  if (loading && !snapshot && !analysis) {
    return <main className="intelligencePage"><header className="intelHeader"><div className="intelIdentity"><h1>Inteligência</h1><p>Entenda o que está acontecendo no seu negócio e onde agir.</p></div><small>{getActiveClientName()} · {formatDate(period.start)} — {formatDate(period.end)}</small></header><PeriodSelector /><div className="intelWorkspace"><p role="status">Carregando sua leitura...</p><IntelligenceSkeleton /></div></main>;
  }

  return (
    <main className="intelligencePage">
      {/* Primeira dobra responde "o que eu preciso saber hoje?": identidade
          curta, período, frescor e ação. Fontes e cobertura vão para o fim. */}
      <PeriodSelector />
      <header className="intelHeader">
        <div className="intelIdentity">
          <h1>Inteligência</h1>
          <p>Entenda o que está acontecendo no seu negócio e onde agir.</p>
        </div>
        <div className="intelHeaderMeta">
          <span><small>Empresa</small>{snapshot?.client.name || getActiveClientName() || "Empresa ativa"}</span>
          <span><small>Período</small>{formatDate(period.start)} — {formatDate(period.end)}</span>
          {/* Frescor do DADO e frescor da ANÁLISE são coisas diferentes e
              aparecem separados: um é sincronização, o outro é a IA. */}
          {dataFreshnessLabel ? (
            <span><small>Dados atualizados</small>{dataFreshnessLabel}</span>
          ) : null}
          {analysisUpdatedLabel ? (
            <span><small>Análise gerada em</small>{analysisUpdatedLabel}</span>
          ) : null}
          <button
            className="btn intelHeaderAction"
            type="button"
            onClick={() => void refreshData()}
            disabled={revalidating || !refreshCooldown.ready}
            data-testid="intel-refresh-data"
            title={cooldownHint(refreshCooldown) || undefined}
          >
            {revalidating ? "Atualizando..." : "Atualizar dados"}
          </button>
          <button
            className="btn btnPrimary intelHeaderAction"
            onClick={() => void refreshAnalysis()}
            disabled={refreshing}
            data-testid="intel-generate"
          >
            {refreshing ? "Gerando análise..." : content ? "Gerar nova análise" : "Gerar análise"}
          </button>
        </div>
        {cooldownHint(refreshCooldown) ? (
          <p className="intelHeaderHint" role="status">{cooldownHint(refreshCooldown)}</p>
        ) : null}
      </header>

      <div className="intelWorkspace" tabIndex={0} aria-label="Análises e conversa" ref={workspaceView}>
      {/* Erro nunca destrói a página: com análise anterior válida, ela
          permanece e o aviso é discreto. */}
      {error ? (
        <div className={content ? "intelInlineWarning" : "intelInlineError"} role={content ? "status" : "alert"} data-testid={content ? "intel-stale-warning" : "intel-error"}>
          <p>Não foi possível concluir esta análise.</p>
          {content ? <p>A última análise válida continua disponível.</p> : null}
          <button className="btn" type="button" disabled={refreshing || asking || revalidating || (retryKind.current === "read" && !refreshCooldown.ready)} title={retryKind.current === "read" ? cooldownHint(refreshCooldown) || undefined : undefined} onClick={() => {
            if (retryKind.current === "question") questionForm.current?.requestSubmit();
            else if (retryKind.current === "read") void refreshData();
            else void refreshAnalysis();
          }}>
            Tentar novamente
          </button>
        </div>
      ) : null}
      {fresherDataAvailable && content ? (
        <p className="intelInlineWarning" role="status" data-testid="intel-fresher-data">
          Há dados mais recentes disponíveis. A análise abaixo é a última gerada.
        </p>
      ) : null}
      {providerConfigured === false || analysis?.status === "configuration_pending" ? (
        <p className="intelInlineWarning" role="status">
          A geração de novas análises está temporariamente indisponível. Os dados da empresa seguem acessíveis.
        </p>
      ) : null}

      {/* Resumo do momento: duas a quatro linhas, sem hero gigante. */}
      {content ? (
        <section className="intelMoment" aria-labelledby="intel-moment-title">
          <h2 id="intel-moment-title">Resumo</h2>
          <p className="intelMomentLead">{content.executive.overall}</p>
          {content.executive.priority_action ? (
            <p className="intelMomentAction">{content.executive.priority_action}</p>
          ) : null}
        </section>
      ) : !error && !messages.length ? (
        <section className="intelMoment intelMomentEmpty" data-testid="intel-empty">
          <h2>O que você quer entender?</h2>
          <p>Escolha um ponto de partida ou escreva sua pergunta abaixo.</p>
          <div className="intelQuestionSuggestions">
            {QUESTIONS.map((suggestion) => <button key={suggestion} type="button" disabled={asking || providerConfigured === false} onClick={() => chooseQuestion(suggestion)}>{suggestion}</button>)}
          </div>
          <button
            className="btn btnPrimary"
            type="button"
            disabled={refreshing}
            onClick={() => void refreshAnalysis()}
            data-testid="intel-generate-empty"
          >
            {refreshing ? "Gerando análise..." : "Gerar análise"}
          </button>
        </section>
      ) : null}

      {displayedMetrics.length ? (
      <section className="intelSection">
        <div className="intelSectionTitle">
          <div><span className="intelEyebrow">Evidências</span><h2>Números importantes</h2></div>
          <p>Ausência, erro e desconexão nunca são apresentados como zero.</p>
        </div>
        <div className="intelMetricGrid">
          {displayedMetrics.map((metric) => (
            <article className={`intelMetric is-${metric.status}`} key={metric.id}>
              <div><span>{metric.label}</span><small>{sourceLabel(metric.source)}</small></div>
              <strong>{formatMetric(metric)}</strong>
              <p>
                {metric.variation_percent == null
                  ? metric.status === "partial"
                    ? "Cobertura parcial do período"
                    : metric.status === "confirmed"
                      ? "Sem base anterior comparável"
                      : "Evidência indisponível"
                  : `${metric.variation_percent > 0 ? "+" : ""}${metric.variation_percent.toLocaleString("pt-BR")}% vs. período anterior`}
              </p>
            </article>
          ))}
        </div>
      </section>
      ) : null}

      {/* Contexto da marca: uma linha, nunca um cartão dominante. */}
      {!businessContextAvailable && canEditBusinessContext ? (
        <p className="intelInlineCta" data-testid="intel-context-cta">
          Melhore esta leitura adicionando contexto estratégico em Administração › Contexto estratégico.
        </p>
      ) : null}

      {/* O que merece decisão primeiro. No máximo três, sempre com evidência:
          menos de três é resposta legítima, não falha. */}
      {movements.length ? (
        <section className="intelSection intelMovements" data-testid="intel-movements">
          <div className="intelSectionTitle">
            <div>
              <span className="intelEyebrow">Prioridade</span>
              <h2>{movements.length === 1 ? "1 movimento que merece sua atenção" : `${movements.length} movimentos que merecem sua atenção`}</h2>
            </div>
            {sourceNames.length ? (
              <p data-testid="intel-source-note">
                Fontes: {sourceNames.join(" · ")}
                {updatedLabel ? ` · atualizado ${updatedLabel}` : ""}
              </p>
            ) : null}
          </div>
          <ol className="intelMovementList">
            {movements.map((insight, index) => (
              <li className={`intelMovement is-${insight.category}`} key={`${insight.title}-${index}`}>
                <span className="intelMovementRank" aria-hidden="true">{index + 1}</span>
                <div className="intelMovementBody">
                  <h3>{insight.title}</h3>
                  <p className="intelMovementFact">
                    <span className="intelInsightBadge is-fact">O que aconteceu</span>
                    <Evidence ids={insight.metric_ids} metrics={metricIndex} />
                  </p>
                  <p className="intelMovementWhy">
                    <span className="intelInsightBadge is-interpretation">Por que importa</span>
                    {insight.interpretation}
                  </p>
                  <p className="intelMovementAction">
                    <span className="intelInsightBadge is-recommendation">O que fazer</span>
                    {insight.action}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {/* Oportunidades só entram aterradas em dado; sem candidata, sem seção. */}
      {opportunities.length ? (
        <section className="intelSection" data-testid="intel-opportunities">
          <div className="intelSectionTitle">
            <div><span className="intelEyebrow">Caminhos</span><h2>Oportunidades</h2></div>
            <p>Cada uma sai de um número do período, não de boa prática genérica.</p>
          </div>
          <div className="intelOpportunityList">
            {opportunities.map((insight, index) => (
              <article key={`${insight.title}-${index}`}>
                <h3>{insight.title}</h3>
                <Evidence ids={insight.metric_ids} metrics={metricIndex} />
                <p>{insight.interpretation}</p>
                <strong>{insight.action}</strong>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {/* Ideias derivadas das recomendações da análise. Ainda não é tarefa,
          calendário nem publicação. */}
      {testIdeas.length ? (
        <section className="intelSection" data-testid="intel-ideas">
          <div className="intelSectionTitle">
            <div><span className="intelEyebrow">Experimentos</span><h2>Ideias para testar</h2></div>
            <p>Hipóteses para avaliar, com a métrica que diz se funcionou.</p>
          </div>
          <div className="intelIdeaList">
            {testIdeas.map((idea) => (
              <article key={idea.title}>
                <h3>{idea.title}</h3>
                {idea.whyNow ? <p><small>Por que agora</small>{idea.whyNow}</p> : null}
                <p><small>Ação</small>{idea.action}</p>
                {idea.hypothesis ? <p><small>Hipótese</small>{idea.hypothesis}</p> : null}
                <p><small>Métrica para acompanhar</small>{idea.metricLabel}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {/* Contexto da marca: convite discreto para quem pode editar, nunca bloqueio. */}
      {!businessContextAvailable && canEditBusinessContext ? (
        <section className="intelSection intelContextCta" data-testid="intel-context-cta">
          <div className="intelSectionTitle">
            <div><span className="intelEyebrow">Contexto</span><h2>Adicionar contexto da marca</h2></div>
            <p>
              Com segmento, público e objetivos preenchidos, a leitura passa a considerar a
              realidade da empresa, não só os números. Em Administração › Contexto estratégico.
            </p>
          </div>
        </section>
      ) : null}



      {content ? (
      <section className="intelSection">
        <div className="intelSectionTitle">
          <div><span className="intelEyebrow">Leitura</span><h2>Avanços, riscos e oportunidades</h2></div>
          <p>Impacto, confiança, fontes e evidências ficam visíveis em cada conclusão.</p>
        </div>
        {content?.insights?.length ? (
          <div className="intelInsightGroups">
            {INSIGHT_GROUPS.map((group) => {
              const items = content.insights.filter((insight) => group.categories.includes(insight.category));
              if (!items.length) return null;
              return (
                <div className="intelInsightGroup" key={group.id}>
                  <h3 className={`intelInsightGroupTitle is-${group.id}`}>{group.title}</h3>
                  <div className="intelInsightGrid">
                    {items.map((insight, index) => (
                      <article className={`intelInsight is-${insight.category}`} key={`${insight.title}-${index}`}>
                        <div className="intelInsightTop">
                          <span>{CATEGORY_LABELS[insight.category]}</span>
                          <small>Impacto {({ high: "alto", medium: "médio", low: "baixo" })[insight.impact]} · confiança {({ high: "alta", medium: "média", low: "baixa" })[insight.confidence]}</small>
                        </div>
                        <h4>{insight.title}</h4>
                        <span className="intelInsightBadge is-fact">Fato</span>
                        <Evidence ids={insight.metric_ids} metrics={metrics} />
                        <span className="intelInsightBadge is-interpretation">Interpretação</span>
                        <p>{insight.interpretation}</p>
                        <span className="intelInsightBadge is-recommendation">Recomendação</span>
                        <div className="intelInsightAction"><strong>{insight.action}</strong><small>{insight.reason}</small></div>
                        <div className="intelTags">{insight.sources.map((source) => <span key={source}>{sourceLabel(source)}</span>)}</div>
                      </article>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : <div className="intelEmpty">Nenhum insight versionado para este período.</div>}
      </section>
      ) : null}

      {snapshot?.crossings.length ? (
      <section className="intelSection">
        <div className="intelSectionTitle">
          <div><span className="intelEyebrow">Visão integrada</span><h2>Cruzamento de plataformas</h2></div>
          <p>Relações observadas não são apresentadas como causalidade.</p>
        </div>
        <div className="intelCrossGrid">
          {(snapshot?.crossings || []).map((crossing) => (
            <article key={crossing.id}>
              <div><h3>{crossing.label}</h3><span>{crossing.status === "available" ? "Disponível" : "Dados insuficientes"}</span></div>
              <Evidence ids={crossing.metrics} metrics={metricMap(snapshot?.metrics || [])} />
              <p>{crossing.note}</p>
            </article>
          ))}
        </div>
      </section>
      ) : null}

      {content ? (
      <section className="intelSection">
        <div className="intelSectionTitle">
          <div><span className="intelEyebrow">Execução</span><h2>Próximos passos</h2></div>
          <p>Recomendações são hipóteses priorizadas, nunca garantias de resultado.</p>
        </div>
        {content?.actions?.length ? (
          <div className="intelActionColumns">
            {(["now", "week", "monitor", "investigate"] as const).map((priority) => (
              <div key={priority}>
                <h3>{PRIORITY_LABELS[priority]}</h3>
                {content.actions.filter((action) => action.priority === priority).map((action, index) => (
                  <article key={`${action.recommendation}-${index}`}>
                    <strong>{action.recommendation}</strong>
                    <p>{action.justification}</p>
                    <small>{action.impact_expected} · confiança {({ high: "alta", medium: "média", low: "baixa" })[action.confidence]}</small>
                  </article>
                ))}
              </div>
            ))}
          </div>
        ) : <div className="intelEmpty">O plano será criado junto com a próxima análise.</div>}
      </section>
      ) : null}

      {content || messages.length ? (
      <section className="intelAssistant">
        <div className="intelAssistantIntro">
          <span className="intelEyebrow">Seu analista</span>
          <h2>{messages.length ? "Sua conversa com o negócio" : "O que você quer entender?"}</h2>
          <p>As respostas usam somente a empresa, o período e as fontes exibidos nesta página.</p>
        </div>
        {!messages.length ? (
        <div className="intelQuestionSuggestions">
          {QUESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" disabled={asking || providerConfigured === false} onClick={() => chooseQuestion(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
        ) : null}
        <div className="intelConversation" aria-live="polite" ref={conversationView}>
          {messages.map((message) => (
            <article className={`intelMessage is-${message.role}`} key={message.id}>
              <small>{message.role === "user" ? "Sua pergunta" : "Mugô Inteligência"}</small>
              {message.role === "user" ? (
                <p>{message.content.question}</p>
              ) : (
                <>
                  <div className="intelAnswerSummary"><span className="intelEyebrow">Resumo</span><h3>{message.content.direct_answer}</h3></div>
                  {message.content.metric_ids?.some((id) => conversationMetrics.has(id)) ? (
                    <section className="intelAnswerMetrics"><h4>Números importantes</h4><Evidence ids={message.content.metric_ids} metrics={conversationMetrics} /></section>
                  ) : null}
                  {message.content.evidence?.length || message.content.attention_points?.length ? (
                    <section className="intelAnswerReading"><h4>Leitura</h4>
                      {message.content.evidence?.length ? <div><h5>Evidências consultadas</h5>{message.content.evidence.map((item, index) => <p key={index}>{item}</p>)}</div> : null}
                      {message.content.attention_points?.length ? <div><h5>Pontos de atenção</h5>{message.content.attention_points.map((item, index) => <p key={index}>{item}</p>)}</div> : null}
                    </section>
                  ) : null}
                  {message.content.recommendations?.length || message.content.next_steps?.length ? (
                    <section className="intelNextSteps"><h4>Próximos passos</h4>
                      {message.content.recommendations?.length ? <div><h5>Recomendações</h5><ul>{message.content.recommendations.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
                      {message.content.next_steps?.length ? <div><h5>Ações sugeridas</h5><ul>{message.content.next_steps.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
                    </section>
                  ) : null}
                  <footer>{formatDate(message.period_start)} — {formatDate(message.period_end)}</footer>
                </>
              )}
            </article>
          ))}
        </div>

        {messages.at(-1)?.role === "assistant" && !asking ? <div className="intelFollowUps" aria-label="Continue a análise">{FOLLOW_UPS.map((suggestion) => <button key={suggestion} type="button" disabled={providerConfigured === false} onClick={() => chooseQuestion(suggestion)}>{suggestion}</button>)}</div> : null}

      </section>
      ) : null}

      {/* Mercado, referências e creators só existem com pesquisa externa real.
          Sem provider conectado, estas seções não são renderizadas — nunca um
          placeholder que pareça funcionalidade. */}
      {marketSignals.length ? (
        <section className="intelSection" data-testid="intel-market">
          <div className="intelSectionTitle">
            <div><span className="intelEyebrow">Pesquisa externa</span><h2>Mercado agora</h2></div>
            <p>Sinais observados fora da operação, com a fonte de cada um.</p>
          </div>
          <div className="intelHistoryList">
            {marketSignals.map((item) => (
              <a className="intelResearchItem" href={item.source_url || undefined} key={item.source_url || item.handle} rel="noreferrer noopener" target="_blank">
                <span><strong>{item.reason_relevant || item.observed_format || "Sinal observado"}</strong><small>{item.platform || "Plataforma não informada"}</small></span>
                <span><strong>{item.public_signal || "Sinal público"}</strong><small>{formatDate(item.researched_at)}</small></span>
              </a>
            ))}
          </div>
        </section>
      ) : null}
      {ugcCreators.length || contentReferences.length ? (
        <section className="intelSection" data-testid="intel-creators">
          <div className="intelSectionTitle">
            <div><span className="intelEyebrow">Pesquisa externa</span><h2>Creators e UGC</h2></div>
            <p>Evidências para avaliação humana. A escolha de quem contratar é sempre sua.</p>
          </div>
          <div className="intelHistoryList">
            {[...ugcCreators, ...contentReferences].map((item) => (
              <a className="intelResearchItem" href={item.source_url || undefined} key={item.source_url || item.handle} rel="noreferrer noopener" target="_blank">
                <span><strong>{item.handle || item.observed_format || "Referência"}</strong><small>{item.platform || "Plataforma não informada"}</small></span>
                <span>
                  <strong>{item.kind === "POTENTIAL_UGC_CREATOR" ? "Creator para avaliar" : "Referência de conteúdo"}</strong>
                  <small>{item.reason_relevant || "Sem motivo informado"}</small>
                </span>
              </a>
            ))}
          </div>
        </section>
      ) : null}

      {/* Fontes são evidência, não produto: ficam no fim, em uma linha. */}
      {sourceNames.length || commerceContext?.provider_label ? (
        <section className="intelSources" aria-label="Fontes da análise" data-testid="intel-sources">
          <h2>Fontes da análise</h2>
          <p className="intelSourcesList">{sourceNames.join(" · ")}</p>
          {sourceCoverage ? <p className="intelSourcesNote">{sourceCoverage}</p> : null}
          {commerceContext?.provider && !commerceContext.official_kpis ? (
            <p className="intelSourcesNote" data-testid="intel-commerce-note">
              Os números de vendas vêm dos pedidos já sincronizados e podem diferir do painel da
              loja.
            </p>
          ) : null}
          {commerceContext?.ambiguous ? (
            <p className="intelSourcesNote">
              Há mais de uma plataforma de vendas conectada; a leitura usa a principal.
            </p>
          ) : null}
          {snapshot?.historical_context?.coverage_start && snapshot.historical_context.coverage_end ? (
            <p className="intelSourcesNote">
              Histórico considerado: {formatDate(snapshot.historical_context.coverage_start)} — {formatDate(snapshot.historical_context.coverage_end)}
            </p>
          ) : null}
        </section>
      ) : null}


      </div>
      {asking || refreshing ? (
        <div className="intelProcessing" role="status" aria-live="polite">
          <span className="intelProcessingDot" aria-hidden="true" />
          <p>Analisando os dados de {snapshot?.client.name || getActiveClientName()}...</p>
        </div>
      ) : null}
        <form className="intelAskForm" onSubmit={submitQuestion} ref={questionForm}>
          <label htmlFor="intel-question">Sua pergunta</label>
          <div>
            <textarea
              id="intel-question"
              ref={questionInput}
              rows={2}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Pergunte sobre seus dados..."
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  if (!asking && providerConfigured !== false) event.currentTarget.form?.requestSubmit();
                }
              }}
              disabled={asking || providerConfigured === false}
            />
            <button className="btn btnPrimary" disabled={asking || !question.trim() || providerConfigured === false}>
              {asking ? "Analisando…" : "Enviar"}
            </button>
          </div>
        </form>
    </main>
  );
}
