import IntelligenceReports from "../components/intelligence/IntelligenceReports";
import { formatMetric, sourceLabel } from "../app/intelligenceReport";
import ConversationHistory from "../components/intelligence/ConversationHistory";
import { useDataHealth } from "../app/DataHealthContext";
import MetricHelp from "../components/data/MetricHelp";
import type { MetricId } from "../app/metricGlossary";
import useSectionDemand from "../hooks/useSectionDemand";
import { readOnce } from "../hooks/dashboard/readOnce";
import PeriodSelector from "../components/data/PeriodSelector";
import PageHeader from "../components/data/PageHeader";
import Delta from "../components/data/Delta";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
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
  describeSources,
  selectMovements,
  selectOpportunities,
} from "../app/intelligencePriority";
import { usePeriod } from "../app/PeriodContext";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "../hooks/dashboard/cache";
import { cooldownFrom, cooldownHint, formatFreshness, hasFresherData } from "../app/dataRefresh";
import "../styles/intelligence.css";


type Props = {
  onLogout: () => void | Promise<void>;
  /**
   * Administração do contexto estratégico (PUT /business-context exige papel
   * de gestão). Gerar análise NÃO depende disto: qualquer membro gera.
   */
  canEditBusinessContext?: boolean;
  conversationUserId?: string | null;
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

// Only persisted, completed analyses from the active tenant can be promoted.
// Failed attempts never replace the last valid diagnosis from the bounded history.
function lastValidAnalysis(records: Array<IntelligenceAnalysisRecord | null>, clientId: string) {
  return records.filter((record): record is IntelligenceAnalysisRecord => Boolean(
    record?.client_id === clientId && record.status === "completed" && record.analysis?.executive?.overall?.trim(),
  )).sort((left, right) =>
    Date.parse(right.completed_at || right.created_at) - Date.parse(left.completed_at || left.created_at),
  )[0] || null;
}

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

const METRIC_STATUS_LABELS: Record<IntelligenceMetric["status"], string> = {
  confirmed: "Confirmado", partial: "Cobertura parcial", unavailable: "Sem evidência",
  disconnected: "Não conectado", error: "Falha na leitura",
};

const PRIORITY_LABELS: Record<IntelligenceAction["priority"], string> = {
  now: "Fazer agora",
  week: "Fazer nesta semana",
  monitor: "Acompanhar",
  investigate: "Investigar",
};

const IMPACT_LABELS: Record<IntelligenceInsight["impact"], string> = { high: "alto", medium: "médio", low: "baixo" };
const CONFIDENCE_LABELS: Record<IntelligenceInsight["confidence"], string> = { high: "alta", medium: "média", low: "baixa" };

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

function failureHint(message: string) {
  if (/INSUFFICIENT|dados suficientes/i.test(message)) return "Ainda não há indicadores suficientes para uma análise confiável neste período.";
  if (/TEMPORALLY|fontes.*compatíveis/i.test(message)) return "As fontes ainda não têm cobertura compatível. Confira as fontes disponíveis e tente novamente mais tarde.";
  if (/TIMEOUT|demorou|tempo.*esgotado/i.test(message)) return "O processamento demorou mais que o esperado. A leitura anterior foi preservada.";
  if (/UNTRUSTED|UNGROUNDED|validar as conclusões/i.test(message)) return "As conclusões não puderam ser validadas. Nenhuma informação rejeitada foi publicada.";
  return "Os dados disponíveis continuam preservados. Tente novamente mais tarde.";
}

function glossaryMetric(metric: IntelligenceMetric): MetricId | undefined {
  if (metric.id === "roas" && metric.source.includes("+")) return "blendedReturn";
  if (metric.id === "conversion_rate" && metric.source === "ga4") return "ga4ConversionRate";
  return undefined;
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
    <ul className="intelEvidence">
      {items.map((metric) => (
        <li key={metric.id}>
          <small>{metric.label}<MetricHelp label={metric.label} metricId={glossaryMetric(metric)} /></small>
          <strong>{formatMetric(metric)}</strong>
          {metric.variation_percent != null ? <Delta change={metric.variation_percent} sentiment={/investment|spend|cpa/.test(metric.id) ? "neutral" : "higher-is-better"} /> : null}
        </li>
      ))}
    </ul>
  );
}

// onLogout segue no tipo por compatibilidade: a saída vive na sidebar global.
export default function Intelligence({ canEditBusinessContext = false, conversationUserId = null }: Props) {
  const health = useDataHealth();
  const { period } = usePeriod();
  const clientId = getActiveClientId();
  const cacheKey = `${clientId}:${period.start}:${period.end}`;
  const cached = workspaceCache.get(cacheKey);
  const [snapshot, setSnapshot] = useState<IntelligenceSnapshot | null>(cached?.snapshot || null);
  const [latestAnalysis, setAnalysis] = useState<IntelligenceAnalysisRecord | null>(cached?.analysis || null);
  const [history, setHistory] = useState<IntelligenceAnalysisRecord[]>(cached?.history || []);
  const analysis = useMemo(
    () => lastValidAnalysis([latestAnalysis, ...history], clientId),
    [latestAnalysis, history, clientId],
  );
  const [providerConfigured, setProviderConfigured] = useState<boolean | null>(
    cached?.providerConfigured ?? null,
  );
  const [loading, setLoading] = useState(!cached);
  const [displayPeriod, setDisplayPeriod] = useState(period);
  const [transitioning, setTransitioning] = useState(false);
  const displayedTenant = useRef(clientId);
  const transitionRef = useRef(transitioning); useLayoutEffect(() => {transitionRef.current = transitioning;}, [transitioning]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<IntelligenceMessage[]>([]);
  const [conversationLoading, setConversationLoading] = useState(Boolean(conversationUserId));
  const [answerSnapshotId, setAnswerSnapshotId] = useState<string | null>(null);
  const [conversationMetrics, setConversationMetrics] = useState<Map<string, IntelligenceMetric>>(new Map());
  const conversationScope = useRef(`${clientId}:${conversationUserId}`);
  if (conversationScope.current !== `${clientId}:${conversationUserId}`) {
    conversationScope.current = `${clientId}:${conversationUserId}`;
    setConversationId(null); setMessages([]); setQuestion(""); setAnswerSnapshotId(null); setConversationMetrics(new Map());
    setConversationLoading(Boolean(conversationUserId));
  }
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
  const detailedContextScope = useRef<string | null>(null);
  const detailsDemand = useSectionDemand(cacheKey, Boolean(snapshot) && !transitioning && displayPeriod.start === period.start && displayPeriod.end === period.end);
  // Navegação da leitura acompanha a rolagem: a seção visível fica marcada.
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const sectionLayout = `${Boolean(analysis)}:${Boolean(snapshot)}:${loading}`;
  useEffect(() => {
    if (typeof window === "undefined") return;
    const ids = ["intel-executive", "intel-indicators", "intel-priorities", "intel-next", "intel-conversation", "intel-reports"];
    let frame = 0;
    const update = () => {
      frame = 0;
      const present = ids.map((id) => document.getElementById(id)).filter((el): el is HTMLElement => Boolean(el));
      if (!present.length) return;
      // A seção atual é a última cujo topo já passou da navegação fixa.
      const passed = present.filter((el) => el.getBoundingClientRect().top <= 140);
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      setActiveSection((atBottom ? present.at(-1) : passed.at(-1) || present[0])?.id || null);
    };
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [sectionLayout]);

  useEffect(() => {
    if (messages.length) conversationView.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [messages.length]);

  function chooseQuestion(value: string) {
    setQuestion(value);
    questionInput.current?.focus();
  }

  // Tenant muda: limpa síncronamente. Período muda no mesmo tenant:
  // mantém a leitura anterior com o rótulo antigo até a substituição atômica.
  if (cacheKeyRef.current !== cacheKey) {
    cacheKeyRef.current = cacheKey;
    requestVersion.current += 1;
    refreshController.current?.abort();
    askController.current?.abort();
    const nextCache = workspaceCache.get(cacheKey);
    const keepPrevious = displayedTenant.current === clientId && !nextCache && Boolean(snapshot || analysis);
    displayedTenant.current = clientId;
    setTransitioning(keepPrevious);
    if (!keepPrevious) {
      setSnapshot(nextCache?.snapshot || null);
      setAnalysis(nextCache?.analysis || null);
      setDisplayPeriod(period);
    }
    setHistory(nextCache?.history || []);
    setProviderConfigured(nextCache?.providerConfigured ?? null);
    setRefreshedAt(nextCache?.refreshedAt || null);
    setLoading(!nextCache && !keepPrevious);
    setError("");
  }

  // Leitura do workspace: a mesma para a abertura da tela e para o botão
  // "Atualizar dados". Só GETs já autorizados — nenhuma mutação, nenhuma IA.
  const loadWorkspace = useCallback((controller: AbortController, detailed = false) => {
    const transitioning = transitionRef.current;
    const version = ++requestVersion.current;
    const currentCache = workspaceCache.get(cacheKey);
    setError("");
    const live = () => !controller.signal.aborted && version === requestVersion.current;
    const persist = (patch: Partial<CachedWorkspace>) => {
      if (!live()) return;
      workspaceCache.set(cacheKey, { snapshot: null, analysis: null, history: [], providerConfigured: null,
        ...currentCache, ...workspaceCache.get(cacheKey), ...patch });
    };
    const contextRead = readOnce(`intelligence-context:${cacheKey}:${detailed}`, () => getIntelligenceContext(period, {includeCommerceDetails: detailed}));
    const historyKey = buildDashboardCacheKey("intelligence-history", {clientId});
    const cachedHistory = !detailed ? readDashboardCache<IntelligenceAnalysisRecord[]>(historyKey) : null;
    const latestRead = readOnce(`intelligence-latest:${cacheKey}`, () => getLatestIntelligenceAnalysis(period));
    if (transitioning) void Promise.allSettled([contextRead, latestRead]).then(([contextResult, latestResult]) => {
      if (!live()) return;
      if (contextResult.status !== "fulfilled" || latestResult.status !== "fulfilled") { setError("Não foi possível atualizar o período. Mantendo a leitura anterior."); return; }
      setSnapshot(contextResult.value.snapshot); setAnalysis(latestResult.value.analysis);
      setProviderConfigured(latestResult.value.provider_configured); setDisplayPeriod(period); setTransitioning(false);
    });
    return Promise.allSettled([
      contextRead.then(result => {
        if (live() && !transitioning) { setDisplayPeriod(period); setSnapshot(result.snapshot); setLoading(false); persist({ snapshot: result.snapshot }); }
        return result;
      }),
      latestRead.then(result => {
        if (live() && !transitioning) { setAnalysis(result.analysis); setProviderConfigured(result.provider_configured);
          if (result.analysis) setLoading(false);
          persist({ analysis: result.analysis, providerConfigured: result.provider_configured }); }
        return result;
      }),
      (cachedHistory ? Promise.resolve({items:cachedHistory}) : readOnce(`intelligence-history:${clientId}:20`, () => getIntelligenceHistory(20))).then(result => {
        if (live()) { setHistory(result.items); writeDashboardCache(historyKey,result.items,120_000); persist({ history: result.items }); }
        return result;
      }),
    ]).then(([contextResult, latestResult, historyResult]) => {
      if (controller.signal.aborted || version !== requestVersion.current) return;
      const nextSnapshot = detailedContextScope.current === cacheKey ? workspaceCache.get(cacheKey)?.snapshot || null :
        contextResult.status === "fulfilled" ? contextResult.value.snapshot : currentCache?.snapshot || null;
      const nextAnalysis =
        latestResult.status === "fulfilled" ? latestResult.value.analysis : currentCache?.analysis || null;
      const nextHistory =
        historyResult.status === "fulfilled" ? historyResult.value.items : currentCache?.history || [];
      const nextProvider =
        latestResult.status === "fulfilled"
          ? latestResult.value.provider_configured
          : currentCache?.providerConfigured ?? null;
      if (!transitioning) { setSnapshot(nextSnapshot); setAnalysis(nextAnalysis); }
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
      if (contextResult.status === "rejected" && latestResult.status === "rejected") {
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

  useEffect(() => {
    if (!detailsDemand.enabled) return;
    let active = true;
    const requestedKey = cacheKey;
    void readOnce(`intelligence-context:${cacheKey}:true`, () => getIntelligenceContext(period, {includeCommerceDetails: true})).then(result => {
      if (!active || cacheKeyRef.current !== requestedKey) return;
      detailedContextScope.current = requestedKey;
      setSnapshot(result.snapshot);
      const current = workspaceCache.get(requestedKey);
      if (current) workspaceCache.set(requestedKey, {...current, snapshot:result.snapshot});
    }).catch(() => { if (active) setError("Não foi possível completar os detalhes. Mantendo a leitura disponível."); });
    return () => {active = false;};
  }, [cacheKey, detailsDemand.enabled, period]);

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
      await loadWorkspace(controller, true);
    } finally {
      setRevalidating(false);
    }
  }, [lastRefreshAt, loadWorkspace, revalidating]);

  const displayedMetrics = useMemo(
    () => analysis ? analysis.metrics_snapshot : snapshot?.metrics || [],
    [analysis, snapshot?.metrics],
  );
  const metrics = useMemo(() => metricMap(displayedMetrics), [displayedMetrics]);
  const content = analysis?.status === "completed" ? analysis.analysis : null;
  const supportedMetric = (id: string) => {
    const metric = metrics.get(id);
    return metric?.value != null && ["confirmed", "partial"].includes(metric.status);
  };
  const visibleActions = [...(content?.actions || [])]
    .filter(action => action.recommendation.trim() && supportedMetric(action.metric_id)).sort((a, b) =>
    ["now", "week", "monitor", "investigate"].indexOf(a.priority) - ["now", "week", "monitor", "investigate"].indexOf(b.priority)).slice(0, 3);
  const commerceContext = snapshot?.commerce_context;
  const metricIndex = metrics;
  // Prioridade a partir dos sinais que já existem na análise: nenhum score
  // numérico inventado e nenhum texto novo gerado aqui.
  const movements = useMemo(
    () => selectMovements(content?.insights?.filter(insight => insight.metric_ids.some(id => {
      const metric = metricIndex.get(id);
      return metric?.value != null && ["confirmed", "partial"].includes(metric.status);
    })), metricIndex),
    [content?.insights, metricIndex]
  );
  const opportunities = useMemo(
    () => selectOpportunities(content?.insights, metricIndex, movements),
    [content?.insights, metricIndex, movements]
  );
  const analysisMatchesContext = !analysis || (
    analysis.period_start === snapshot?.period.start && analysis.period_end === snapshot?.period.end
  );
  const sourceNames = useMemo(() => analysis?.sources.length
    ? describeSources(analysis)
    : analysisMatchesContext ? describeSources(snapshot) : [], [analysis, analysisMatchesContext, snapshot]);
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

  const contextUpdatedAt = Date.parse(snapshot?.business_context?.updated_at || "");
  const analysisCreatedAt = Date.parse(analysis?.created_at || "");
  const analysisPredatesContext = Boolean(analysis && snapshot?.client.id === clientId
    && Number.isFinite(contextUpdatedAt) && Number.isFinite(analysisCreatedAt)
    && analysisCreatedAt < contextUpdatedAt);

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

  const restoreConversation = useCallback((id: string, restored: IntelligenceMessage[]) => {
    askController.current?.abort();
    setConversationId(id || null); setMessages(restored); setQuestion("");
    setAnswerSnapshotId(null); setConversationMetrics(new Map()); setAsking(false);
  }, []);

  async function submitQuestion(event: FormEvent) {
    event.preventDefault();
    const clean = question.trim();
    if (!clean || asking || conversationLoading) return;
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
      if (controller.signal.aborted || getActiveClientId() !== clientId) return;
      if (result.snapshot.client.id !== clientId) throw new Error("Não foi possível validar a empresa desta resposta.");
      setAnswerSnapshotId(result.assistant_message.id);
      setConversationMetrics(metricMap(result.snapshot.metrics));
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

  const companyName = snapshot?.client.name || getActiveClientName() || "Empresa ativa";
  const periodLabel = `${formatDate(displayPeriod.start)} — ${formatDate(displayPeriod.end)}`;
  const shownTitles = new Set(movements.map((insight) => insight.title));
  // "Outras leituras": só o que ainda não apareceu em "Onde agir".
  const remainingInsights = (content?.insights || []).filter((insight) => !shownTitles.has(insight.title));
  const remainingOpportunityTitles = new Set(opportunities.map((insight) => insight.title));
  const actionPriorities = (["now", "week", "monitor", "investigate"] as const)
    .filter((priority) => visibleActions.some((action) => action.priority === priority));

  // Um botão de gerar por vez: no estado vazio, o convite do próprio estado
  // vazio é a ação; com análise (ou com erro), o botão fica no cabeçalho.
  const emptyStateShown = !content && !error && !messages.length && !loading;
  const header = (
    <div className="intelHeader">
      <PageHeader
        company={companyName}
        title="Inteligência & Relatórios"
        subnav={<p className="intelLede">Entenda o que está acontecendo no seu negócio e onde agir.</p>}
        dateline={
          <span className="intelHeaderMeta">
            <span>Período exibido {periodLabel}</span>
            {/* Frescor do DADO e frescor da ANÁLISE são coisas diferentes e
                aparecem separados: um é sincronização, o outro é a IA. */}
            {analysis ? <span>Análise gerada em {analysisUpdatedLabel}</span> : null}
            {!health && dataFreshnessLabel ? <span>Dados atualizados {dataFreshnessLabel}</span> : null}
          </span>
        }
        controls={<PeriodSelector />}
      />
      <div className="intelHeaderActions">
        {!emptyStateShown ? (
          <button
            className="ds-button is-primary"
            onClick={() => void refreshAnalysis()}
            disabled={refreshing || transitioning || loading}
            data-testid="intel-generate"
          >
            {refreshing ? "Gerando análise..." : content ? "Gerar nova análise" : "Gerar análise"}
          </button>
        ) : null}
        <button
          className="ds-button is-quiet"
          type="button"
          onClick={() => void refreshData()}
          disabled={revalidating || !refreshCooldown.ready || loading}
          data-testid="intel-refresh-data"
          title={cooldownHint(refreshCooldown) || undefined}
        >
          {revalidating ? "Atualizando..." : "Atualizar dados"}
        </button>
        {cooldownHint(refreshCooldown) ? <p className="intelHeaderHint" role="status">{cooldownHint(refreshCooldown)}</p> : null}
      </div>
    </div>
  );

  if (loading && !snapshot && !analysis) {
    return (
      <main className="intelligencePage">
        {header}
        <div className="intelWorkspace"><p role="status" className="ds-status">Carregando sua leitura...</p><IntelligenceSkeleton /></div>
      </main>
    );
  }

  return (
    <main className="intelligencePage">
      {header}

      <nav className="intelReadingNav" aria-label="Navegar pelo diagnóstico">
        {[
          content ? ["intel-executive", "Resumo"] : null,
          displayedMetrics.length ? ["intel-indicators", "Números"] : null,
          movements.length ? ["intel-priorities", "Onde agir"] : null,
          content ? ["intel-next", "Próximos passos"] : null,
          ["intel-conversation", "Conversa com IA"],
          ["intel-reports", "Relatórios"],
        ].filter((item): item is string[] => Boolean(item)).map(([id, label]) => (
          <a key={id} href={`#${id}`} aria-current={activeSection === id ? "location" : undefined}>{label}</a>
        ))}
      </nav>

      <div className="intelWorkspace" ref={workspaceView}>
      {transitioning ? <p role="status" className="ds-status">{error ? "Período não atualizado. Exibindo a leitura anterior." : "Atualizando período... Exibindo a leitura anterior até a nova ficar disponível."}</p> : null}

      {/* Avisos: uma pilha só, no topo, sem cartões. Erro nunca destrói a
          página: com análise anterior válida, ela permanece. */}
      {error ? (
        <div className={`ds-notice ${content ? "is-warning intelInlineWarning" : "is-negative intelInlineError"}`} role={content ? "status" : "alert"} data-testid={content ? "intel-stale-warning" : "intel-error"}>
          <p className="ds-noticeTitle">Não foi possível concluir esta análise.</p>
          <p className="ds-noticeText">{failureHint(error)}{content ? " A última análise válida continua disponível." : ""}</p>
          <div className="ds-noticeActions">
            <button className="ds-button" type="button" disabled={refreshing || asking || revalidating || (retryKind.current === "read" && !refreshCooldown.ready)} title={retryKind.current === "read" ? cooldownHint(refreshCooldown) || undefined : undefined} onClick={() => {
              if (retryKind.current === "question") questionForm.current?.requestSubmit();
              else if (retryKind.current === "read") void refreshData();
              else void refreshAnalysis();
            }}>
              Tentar novamente
            </button>
          </div>
        </div>
      ) : null}
      {analysisPredatesContext ? (
        <div className="ds-notice is-warning intelInlineWarning" role="status" data-testid="intel-context-updated">
          <p className="ds-noticeText">O contexto de negócio foi atualizado depois desta análise. Ela ainda não considera essas alterações.</p>
          <div className="ds-noticeActions">
            <button className="ds-button" type="button" disabled={refreshing || transitioning || providerConfigured === false}
              onClick={() => void refreshAnalysis()}>Gerar análise com contexto atualizado</button>
          </div>
        </div>
      ) : null}
      {fresherDataAvailable && content ? (
        <p className="ds-notice intelInlineWarning" role="status" data-testid="intel-fresher-data">
          Há dados mais recentes disponíveis. A análise abaixo é a última gerada.
        </p>
      ) : null}
      {content && analysis?.data_quality.message?.startsWith("Análise parcial:") ? (
        <p className="ds-notice is-warning intelInlineWarning" role="status" data-testid="intel-partial-analysis">{analysis.data_quality.message}</p>
      ) : null}
      {providerConfigured === false || latestAnalysis?.status === "configuration_pending" ? (
        <p className="ds-notice is-warning intelInlineWarning" role="status">
          A geração de novas análises está temporariamente indisponível. Os dados da empresa seguem acessíveis.
        </p>
      ) : null}

      {/* 1. A leitura do período, em uma frase grande. Fontes e números ficam
          abaixo, cada um em um lugar só. */}
      {content ? (
        <section id="intel-executive" className="intelMoment" aria-labelledby="intel-moment-title">
          <h2 id="intel-moment-title" className="ds-srOnly">Resumo executivo</h2>
          <p className="intelBriefLabel" aria-hidden="true">O período em uma frase</p>
          <p className="intelMomentLead">{content.executive.overall}</p>
          <div className="intelBriefFoot">
            {content.executive.priority_action ? (
              <div className="intelMomentAction"><span>Próxima decisão</span><p>{content.executive.priority_action}</p></div>
            ) : null}
            <div className="intelBriefLinks">
              {movements.length ? <a href="#intel-priorities" className="intelBriefCta">Ver onde agir</a> : null}
              {analysis?.data_quality.message ? (
                <details className="intelDisclosure intelMomentDetails">
                  <summary>Cobertura e limitações</summary>
                  <p data-testid="intel-diagnosis-limitations">{analysis.data_quality.message}</p>
                </details>
              ) : null}
            </div>
          </div>
        </section>
      ) : !error && !messages.length ? (
        <section className="intelMoment intelMomentEmpty" data-testid="intel-empty">
          <h2 className="intelEmptyLead">Ainda não há análise válida</h2>
          <p className="intelBriefText">Gere uma análise para ler o período de {companyName} em uma frase, com as prioridades e os próximos passos. Nada é gerado automaticamente ao abrir esta tela.</p>
          <div className="intelBriefLinks">
            <button
              className="intelBriefCta"
              type="button"
              disabled={refreshing || transitioning}
              onClick={() => void refreshAnalysis()}
              data-testid="intel-generate-empty"
            >
              {refreshing ? "Gerando análise..." : "Gerar análise"}
            </button>
          </div>
        </section>
      ) : null}

      {/* Contexto da marca: convite discreto e único, só para quem pode editar. */}
      {!businessContextAvailable && canEditBusinessContext ? (
        <p className="intelInlineCta" data-testid="intel-context-cta">
          Melhore esta leitura adicionando contexto estratégico em Administração › Contexto estratégico: com segmento, público e objetivos, a análise considera a realidade da empresa, não só os números.
        </p>
      ) : null}

      {/* 2. Números do período: o ÚNICO lugar com o quadro completo. Período e
          fontes aparecem uma vez, no cabeçalho da seção. */}
      {displayedMetrics.length ? (
        <section id="intel-indicators" className="ds-section intelBlock">
          <div className="ds-sectionHead">
            <div className="ds-sectionHeadText">
              <h2 className="ds-sectionTitle">Números do período</h2>
              <p className="ds-caption intelSourceLine" data-testid="intel-source-note">
                {content ? (
                  // O período exibido já está no cabeçalho: aqui ele só aparece
                  // quando a análise salva cobre outro intervalo.
                  <span data-testid="intel-diagnosis-period" className={analysis?.period_start === displayPeriod.start && analysis?.period_end === displayPeriod.end ? "ds-srOnly" : undefined}>
                    Análise de {formatDate(analysis?.period_start)} — {formatDate(analysis?.period_end)}
                  </span>
                ) : null}
                {sourceNames.length ? <span data-testid="intel-diagnosis-sources">Fontes: {sourceNames.join(" · ")}</span> : null}
                {!health && analysisMatchesContext && updatedLabel ? <span>atualizado {updatedLabel}</span> : null}
              </p>
            </div>
            <p className="ds-caption">Ausência, erro e desconexão nunca são apresentados como zero.</p>
          </div>
          <div className="intelMetricGrid">
            {displayedMetrics.map((metric) => (
              <article className={`intelMetric is-${metric.status}`} key={metric.id}>
                <span className="intelMetricLabel">{metric.label}<MetricHelp label={metric.label} metricId={glossaryMetric(metric)} /></span>
                <strong className="intelMetricValue">{formatMetric(metric)}</strong>
                <span className="intelMetricDelta">
                  {metric.variation_percent == null
                    ? <span className="ds-delta">{metric.status === "partial" ? "Cobertura parcial" : metric.status === "confirmed" ? "Sem base anterior" : "Evidência indisponível"}</span>
                    : <Delta change={metric.variation_percent} sentiment={/investment|spend|cpa/.test(metric.id) ? "neutral" : "higher-is-better"} />}
                </span>
                {metric.value != null && metric.previous_value != null && metric.value >= 0 && metric.previous_value >= 0 && metric.variation_percent != null ? (
                  <span className="intelMetricCompare" aria-label={`Período anterior: ${formatMetric({ ...metric, value: metric.previous_value })}`}>
                    <span className="intelMetricBar is-current"><i style={{ width: `${(metric.value / Math.max(metric.value, metric.previous_value, 1e-9)) * 100}%` }} /></span>
                    <span className="intelMetricBar is-previous"><i style={{ width: `${(metric.previous_value / Math.max(metric.value, metric.previous_value, 1e-9)) * 100}%` }} /></span>
                    <small>Anterior {formatMetric({ ...metric, value: metric.previous_value })}</small>
                  </span>
                ) : null}
                <small className="intelMetricSource">
                  {sourceLabel(metric.source)}
                  {metric.status !== "confirmed" ? <span className={`intelMetricStatus is-${metric.status}`}> · {METRIC_STATUS_LABELS[metric.status]}</span> : null}
                </small>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {/* 3. Onde agir: no máximo três, sempre com evidência. Menos de três é
          resposta legítima, não falha. */}
      {movements.length ? (
        <section id="intel-priorities" className="ds-section intelBlock" data-testid="intel-movements">
          <div className="ds-sectionHead">
            <div className="ds-sectionHeadText">
              <h2 className="ds-sectionTitle">{movements.length === 1 ? "1 movimento que merece sua atenção" : `${movements.length} movimentos que merecem sua atenção`}</h2>
              <p className="ds-caption">Ordenados por risco, impacto e confiança. Hipóteses a validar, nunca causalidade comprovada.</p>
            </div>
          </div>
          <ol className="intelMovementList">
            {movements.map((insight, index) => (
              <li className={`intelMovement is-${insight.category}`} key={`${insight.title}-${index}`}>
                <span className="intelMovementRank">Prioridade {index + 1}</span>
                <div className="intelMovementHead">
                  <span className={`intelCategory is-${insight.category}`}>{CATEGORY_LABELS[insight.category]}</span>
                  <h3>{insight.title}</h3>
                  <small className="intelMovementMeta">Impacto {IMPACT_LABELS[insight.impact]} · confiança {CONFIDENCE_LABELS[insight.confidence]}{insight.sources.length ? ` · ${insight.sources.map(sourceLabel).join(", ")}` : ""}</small>
                </div>
                <div className="intelMovementBody">
                  <div className="intelMovementFact">
                    <span className="intelInsightBadge is-fact">O que aconteceu</span>
                    <Evidence ids={insight.metric_ids} metrics={metricIndex} />
                  </div>
                  <p className="intelMovementWhy">
                    <span className="intelInsightBadge is-interpretation">Por que importa (hipótese a validar)</span>
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

      {/* 4. Próximos passos: recomendações da análise com a métrica que diz se
          funcionou. Substitui "Ideias para testar", que repetia o mesmo texto. */}
      {content ? (
        <section id="intel-next" className="ds-section intelBlock" data-testid="intel-recommendations">
          <div className="ds-sectionHead">
            <div className="ds-sectionHeadText">
              <h2 className="ds-sectionTitle">Próximos passos</h2>
              <p className="ds-caption">Recomendações são hipóteses priorizadas, nunca garantias de resultado.</p>
            </div>
          </div>
          {visibleActions.length ? (
            <div className="intelActionList">
              {actionPriorities.map((priority) => (
                <div className={`intelActionGroup is-${priority}`} key={priority}>
                  <h3 className="intelActionPriority">{PRIORITY_LABELS[priority]}</h3>
                  <div>
                    {visibleActions.filter((action) => action.priority === priority).map((action, index) => {
                      const tracked = metricIndex.get(action.metric_id);
                      return (
                        <article className="intelAction" key={`${action.recommendation}-${index}`}>
                          <strong className="intelActionTitle">{action.recommendation}</strong>
                          {action.justification ? <p>{action.justification}</p> : null}
                          <dl className="intelActionFacts">
                            {tracked ? <div className="intelActionTracked"><dt>Métrica para acompanhar</dt><dd><Evidence ids={[action.metric_id]} metrics={metricIndex} /></dd></div> : null}
                            {action.impact_expected ? <div><dt>Resultado esperado (hipótese)</dt><dd>{action.impact_expected}</dd></div> : null}
                            <div><dt>Confiança</dt><dd>{CONFIDENCE_LABELS[action.confidence]}{action.sources.length ? ` · ${action.sources.map(sourceLabel).join(", ")}` : ""}</dd></div>
                          </dl>
                        </article>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : <p className="ds-emptyLine">Não há ações com evidências disponíveis nesta análise.</p>}
        </section>
      ) : null}

      {/* 5. O restante da leitura, sem repetir o que já está em "Onde agir". */}
      {content && remainingInsights.length ? (
        <details className="intelDisclosure intelFullReading" data-testid="intel-full-reading">
          <summary>Outras leituras do período <span>{remainingInsights.length} {remainingInsights.length === 1 ? "conclusão" : "conclusões"} além das prioridades</span></summary>
          <div className="intelInsightGroups">
            {INSIGHT_GROUPS.map((group) => {
              const items = remainingInsights.filter((insight) => group.categories.includes(insight.category));
              if (!items.length) return null;
              const isOpportunity = group.id === "opportunity" && items.some((insight) => remainingOpportunityTitles.has(insight.title));
              return (
                <div className="intelInsightGroup" key={group.id} data-testid={isOpportunity ? "intel-opportunities" : undefined}>
                  <h3 className={`intelInsightGroupTitle is-${group.id}`}>{group.title}</h3>
                  <ul className="intelInsightRows">
                    {items.map((insight, index) => (
                      <li className={`intelInsight is-${insight.category}`} key={`${insight.title}-${index}`}>
                        <div className="intelInsightTop">
                          <h4>{insight.title}</h4>
                          <small>{CATEGORY_LABELS[insight.category]} · impacto {IMPACT_LABELS[insight.impact]} · confiança {CONFIDENCE_LABELS[insight.confidence]}{insight.sources.length ? ` · ${insight.sources.map(sourceLabel).join(", ")}` : ""}</small>
                        </div>
                        <span className="intelInsightBadge is-fact">Fato</span>
                        <Evidence ids={insight.metric_ids} metrics={metrics} />
                        <p><span className="intelInsightBadge is-interpretation">Interpretação</span>{insight.interpretation}</p>
                        <p className="intelInsightAction"><span className="intelInsightBadge is-recommendation">Recomendação</span>{insight.action}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </details>
      ) : null}

      {snapshot?.crossings.length ? (
        <section className="ds-section intelBlock">
          <div className="ds-sectionHead">
            <div className="ds-sectionHeadText">
              <h2 className="ds-sectionTitle">Cruzamento de plataformas</h2>
              <p className="ds-caption">Relações observadas não são apresentadas como causalidade.</p>
            </div>
          </div>
          <ul className="intelCrossList">
            {(snapshot?.crossings || []).map((crossing) => (
              <li key={crossing.id}>
                <div className="intelCrossHead">
                  <h3>{crossing.label}</h3>
                  <small>{crossing.status === "available" ? "Disponível" : "Dados insuficientes"}</small>
                </div>
                <p>{crossing.note}</p>
                <Evidence ids={crossing.metrics} metrics={metricMap(snapshot?.metrics || [])} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Mercado, referências e creators só existem com pesquisa externa real.
          Sem provider conectado, estas seções não são renderizadas — nunca um
          placeholder que pareça funcionalidade. */}
      {marketSignals.length ? (
        <section className="ds-section intelBlock" data-testid="intel-market">
          <div className="ds-sectionHead"><div className="ds-sectionHeadText">
            <h2 className="ds-sectionTitle">Mercado agora</h2>
            <p className="ds-caption">Sinais observados fora da operação, com a fonte de cada um.</p>
          </div></div>
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
        <section className="ds-section intelBlock" data-testid="intel-creators">
          <div className="ds-sectionHead"><div className="ds-sectionHeadText">
            <h2 className="ds-sectionTitle">Creators e UGC</h2>
            <p className="ds-caption">Evidências para avaliação humana. A escolha de quem contratar é sempre sua.</p>
          </div></div>
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

      {/* 6. Conversa: o composer fica logo abaixo, como continuação natural. */}
      <section id="intel-conversation" className="ds-section intelBlock intelAssistant">
        <div className="ds-sectionHead intelAssistantIntro">
          <div className="ds-sectionHeadText">
            <h2 className="ds-sectionTitle">{messages.length ? "Sua conversa com o negócio" : "Pergunte aos seus dados"}</h2>
            <p className="ds-caption">Respostas com os dados de {companyName} em {periodLabel}.{!analysisMatchesContext ? " A análise salva acima se refere a outro período." : ""}</p>
          </div>
        </div>
        <ConversationHistory key={`${clientId}:${conversationUserId}`} clientId={clientId} userId={conversationUserId}
          activeId={conversationId} revision={answerSnapshotId || ""} busy={asking}
          onRestore={restoreConversation} onLoadingChange={setConversationLoading} />
        {messages.length && !answerSnapshotId ? <p className="ds-notice intelInlineWarning" role="status">Conversa restaurada do histórico. As respostas mantêm suas datas originais e não são evidências numéricas atuais. Para consultar outro período, selecione-o antes de perguntar.</p> : null}
        {messages.at(-1)?.role === "user" && !asking ? <p role="status" className="ds-status">A última pergunta não tem resposta salva nesta conversa. Você pode reformulá-la ou enviá-la novamente.</p> : null}
        {!messages.length ? (
        <div className="intelQuestionSuggestions" aria-label="Sugestões de pergunta">
          {QUESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" disabled={asking || conversationLoading || transitioning || providerConfigured === false} onClick={() => chooseQuestion(suggestion)}>
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
                  {message.content.attention_points?.some(item => /resposta parcial|análise parcial/i.test(item)) ? <p className="intelAnswerPartial" role="status">Resposta parcial · confira as limitações desta leitura.</p> : null}
                  <div className="intelAnswerSummary"><span className="intelKicker">Resumo</span><h3>{message.content.direct_answer}</h3></div>
                  {message.id === answerSnapshotId && message.content.metric_ids?.some((id) => conversationMetrics.has(id)) ? (
                    <section className="intelAnswerMetrics"><h4>Números importantes</h4><Evidence ids={message.content.metric_ids} metrics={conversationMetrics} /></section>
                  ) : null}
                  {message.content.evidence?.length || message.content.attention_points?.length ? (
                    <section className="intelAnswerReading"><h4>Leitura</h4>
                      {message.content.evidence?.length ? <details className="intelDisclosure"><summary>Evidências consultadas</summary>{message.content.evidence.map((item, index) => <p key={index}>{item}</p>)}</details> : null}
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

        {messages.at(-1)?.role === "assistant" && !asking ? <div className="intelFollowUps" aria-label="Continue a análise">{FOLLOW_UPS.map((suggestion) => <button key={suggestion} type="button" disabled={conversationLoading || providerConfigured === false} onClick={() => chooseQuestion(suggestion)}>{suggestion}</button>)}</div> : null}
      </section>
      </div>

      {asking || refreshing ? (
        <div className="intelProcessing" role="status" aria-live="polite">
          <span className="intelProcessingDot" aria-hidden="true" />
          <p>Analisando os dados de {companyName}...</p>
        </div>
      ) : null}
      <form className="intelAskForm" onSubmit={submitQuestion} ref={questionForm}>
        <label htmlFor="intel-question" className="ds-srOnly">Sua pergunta</label>
        <div>
          <textarea
            id="intel-question"
            ref={questionInput}
            rows={2}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={`Pergunte sobre os dados de ${companyName}...`}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (!asking && !conversationLoading && providerConfigured !== false) event.currentTarget.form?.requestSubmit();
              }
            }}
            disabled={asking || conversationLoading || transitioning || providerConfigured === false}
          />
          <button className="ds-button is-primary" disabled={asking || conversationLoading || transitioning || !question.trim() || providerConfigured === false}>
            {asking ? "Analisando…" : "Enviar"}
          </button>
        </div>
        <small className="intelAskHint">Enter envia · Shift + Enter quebra a linha</small>
      </form>

      {/* 7. Relatórios recorrentes para o cliente: no fim, não antes do título. */}
      <div id="intel-reports" className="intelReports">
        <IntelligenceReports key={clientId} clientId={clientId} clientName={companyName}
          initialDate={period.start} providerConfigured={providerConfigured} />
      </div>

      {/* Fontes são evidência, não produto: ficam no fim, recolhidas. */}
      {sourceNames.length || commerceContext?.provider_label ? (
        <section ref={detailsDemand.observe} className="intelSources" aria-label="Fontes da análise" data-testid="intel-sources">
          <details className="intelDisclosure"><summary>Fontes e detalhes técnicos da análise</summary>
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
          </details>
        </section>
      ) : null}
    </main>
  );
}
