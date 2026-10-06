import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getComments, getMedia, getStories } from "../../app/api";
import { type DashboardSnapshot, useDashboardSnapshot } from "../../app/DashboardDataContext";
import type {
  CommentItem,
  DashboardResponse,
  IgMediaItem,
  StoryItem,
  TopWord,
} from "../../app/types";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "./cache";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import { readOnce } from "./readOnce";

type SummaryData = {
  dash: DashboardResponse | null;
  media: IgMediaItem[];
  comments: CommentItem[];
  commentsTotal: number;
  topWords: TopWord[];
  stories: StoryItem[];
  storiesAvailable: boolean;
  storiesMessage: string | null;
  paid: null;
};

type StoriesCachePayload = {
  stories: StoryItem[];
  available: boolean;
  message: string | null;
};

type SectionState = {
  dash: boolean;
  media: boolean;
  comments: boolean;
  stories: boolean;
};

type SectionErrors = {
  dash: string | null;
  media: string | null;
  comments: string | null;
  stories: string | null;
};

type SectionTimestamps = {
  dash: string | null;
  media: string | null;
  comments: string | null;
  stories: string | null;
};

type Params = {
  isAuthenticated: boolean;
  activeClientId: string;
  activeConnectionId?: string | null;
  secondaryEnabled?: boolean;
  commentsEnabled?: boolean;
  autoLoadStories?: boolean;
  period?: DashboardPeriod | null;
};

type ReloadOptions = {
  snapshot?: DashboardSnapshot;
  force?: boolean;
  includeSecondary?: boolean;
  secondaryOnly?: boolean;
  loadStories?: boolean;
  onlyStories?: boolean;
};

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function emptySectionState(): SectionState {
  return { dash: false, media: false, comments: false, stories: false };
}

function emptySectionErrors(): SectionErrors {
  return { dash: null, media: null, comments: null, stories: null };
}

function emptyTimestamps(): SectionTimestamps {
  return { dash: null, media: null, comments: null, stories: null };
}

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export default function useDashboardSummary({
  isAuthenticated,
  activeClientId,
  activeConnectionId,
  secondaryEnabled = true,
  commentsEnabled = true,
  autoLoadStories = false,
  period,
}: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
  const model = useDashboardSnapshot(safePeriod.start, safePeriod.end);
  const resolvedConnectionId = useMemo(
    () => String(activeConnectionId || "").trim(),
    [activeConnectionId]
  );
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const dashCacheKey = useMemo(
    () =>
      buildDashboardCacheKey("summary-dash", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, resolvedConnectionId, safePeriod.end, safePeriod.start]
  );
  const mediaCacheKey = useMemo(
    () =>
      buildDashboardCacheKey("summary-media", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, resolvedConnectionId, safePeriod.end, safePeriod.start]
  );
  const commentsCacheKey = useMemo(
    () =>
      buildDashboardCacheKey("summary-comments", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, resolvedConnectionId, safePeriod.end, safePeriod.start]
  );
  const storiesCacheKey = useMemo(
    () =>
      buildDashboardCacheKey("summary-stories", {
        clientId: activeClientId,
        connectionId: resolvedConnectionId || "-",
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, resolvedConnectionId, safePeriod.end, safePeriod.start]
  );

  const cachedInitial = useMemo<SummaryData>(
    () => {
      const cachedComments = readDashboardCache<{ comments: CommentItem[]; commentsTotal?: number; topWords: TopWord[] }>(commentsCacheKey);
      const cachedStoriesRaw = readDashboardCache<StoryItem[] | StoriesCachePayload>(storiesCacheKey);
      const hasCachedStories =
        Array.isArray(cachedStoriesRaw) ||
        (typeof cachedStoriesRaw === "object" && cachedStoriesRaw !== null);
      const cachedStories = Array.isArray(cachedStoriesRaw)
        ? {
            stories: arrayOrEmpty<StoryItem>(cachedStoriesRaw),
            available: true,
            message: null,
          }
        : {
            stories: arrayOrEmpty<StoryItem>(cachedStoriesRaw?.stories),
            available: cachedStoriesRaw?.available === false ? false : true,
            message:
              typeof cachedStoriesRaw?.message === "string" && cachedStoriesRaw.message.trim()
                ? cachedStoriesRaw.message
                : null,
          };
      return {
        dash: readDashboardCache<DashboardResponse>(dashCacheKey),
        media: arrayOrEmpty<IgMediaItem>(readDashboardCache<IgMediaItem[]>(mediaCacheKey)),
        comments: arrayOrEmpty<CommentItem>(cachedComments?.comments),
        commentsTotal:
          typeof cachedComments?.commentsTotal === "number"
            ? cachedComments.commentsTotal
            : arrayOrEmpty<CommentItem>(cachedComments?.comments).length,
        topWords: arrayOrEmpty<TopWord>(cachedComments?.topWords),
        stories: cachedStories.stories,
        storiesAvailable: hasCachedStories ? cachedStories.available : autoLoadStories,
        storiesMessage: hasCachedStories
          ? cachedStories.message
          : autoLoadStories
            ? null
            : "Stories ao vivo ficam sob demanda. Use “Tentar novamente” para consultar a API.",
        paid: null,
      };
    },
    [autoLoadStories, commentsCacheKey, dashCacheKey, mediaCacheKey, storiesCacheKey]
  );

  const [data, setData] = useState<SummaryData>(cachedInitial);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [refreshingSummary, setRefreshingSummary] = useState(false);
  const [sectionLoading, setSectionLoading] = useState<SectionState>(emptySectionState);
  const [sectionRefreshing, setSectionRefreshing] = useState<SectionState>(emptySectionState);
  const [sectionErrors, setSectionErrors] = useState<SectionErrors>(emptySectionErrors);
  const [sectionUpdatedAt, setSectionUpdatedAt] = useState<SectionTimestamps>(emptyTimestamps);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const dataRef = useRef<SummaryData>(cachedInitial);
  const autoPrimaryKeyRef = useRef("");
  const autoSecondaryKeyRef = useRef("");
  const cachedInitialRef = useRef(cachedInitial);

  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  // Troca de empresa/conexão nunca pode deixar o resumo do tenant anterior
  // visível — nem por um frame. `cachedInitial` é um novo objeto sempre que
  // client_id, conexão, período ou autoLoadStories mudam (useMemo acima);
  // comparamos por referência e resetamos de forma síncrona DURANTE o
  // render (não em useEffect, que só roda após o commit), invalidando
  // qualquer resposta em voo do contexto anterior.
  if (cachedInitialRef.current !== cachedInitial) {
    cachedInitialRef.current = cachedInitial;
    abortRef.current?.abort();
    requestRef.current += 1;
    dataRef.current = cachedInitial;
    setData(cachedInitial);
    setSectionErrors(emptySectionErrors());
    setSummaryError(null);
    autoPrimaryKeyRef.current = "";
    autoSecondaryKeyRef.current = "";
  }

  const reloadSummary = useCallback(async (options?: ReloadOptions) => {
    if (!isAuthenticated || !activeClientId) return null;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const reqId = ++requestRef.current;
    const currentData = dataRef.current;
    const includeSecondary = options?.includeSecondary ?? false;
    const secondaryOnly = !!options?.secondaryOnly;
    const includeStories = options?.loadStories ?? autoLoadStories;
    const onlyStories = !!options?.onlyStories;
    const hasExistingData =
      Boolean(currentData.dash) ||
      currentData.media.length > 0 ||
      currentData.comments.length > 0 ||
      currentData.stories.length > 0;

    if (!secondaryOnly) {
      setLoadingSummary(!hasExistingData);
      setRefreshingSummary(hasExistingData);
    }
    setSummaryError(null);
    setSectionErrors((previous) =>
      secondaryOnly
        ? { ...previous, media: null, comments: null, stories: null }
        : emptySectionErrors()
    );
    setSectionLoading({
      dash: secondaryOnly ? false : !currentData.dash,
      media: includeSecondary && !onlyStories && currentData.media.length === 0,
      comments: includeSecondary && commentsEnabled && !onlyStories && currentData.comments.length === 0,
      stories: includeSecondary && includeStories && currentData.stories.length === 0,
    });
    setSectionRefreshing({
      dash: secondaryOnly ? false : Boolean(currentData.dash),
      media: includeSecondary && !onlyStories && currentData.media.length > 0,
      comments: includeSecondary && !onlyStories && currentData.comments.length > 0,
      stories: includeSecondary && includeStories && currentData.stories.length > 0,
    });
    const encounteredErrors = emptySectionErrors();

    const markSectionDone = (key: keyof SectionState, error: string | null = null) => {
      if (reqId !== requestRef.current) return;
      encounteredErrors[key] = error;
      setSectionLoading((previous) => ({ ...previous, [key]: false }));
      setSectionRefreshing((previous) => ({ ...previous, [key]: false }));
      if (error) {
        setSectionErrors((previous) => ({ ...previous, [key]: error }));
      }
    };

    const markSectionSuccess = (key: keyof SectionState) => {
      if (reqId !== requestRef.current) return;
      setSectionUpdatedAt((previous) => ({ ...previous, [key]: new Date().toISOString() }));
      markSectionDone(key, null);
    };

    const loadDash = async () => {
      try {
        const persisted = (options?.snapshot?.daily || model.daily).filter(row => row.metric_date >= safePeriod.start && row.metric_date <= safePeriod.end);
        const metric_coverage = Object.fromEntries(Object.entries({ impressions: "instagram_impressions", reach: "instagram_reach", total_interactions: "instagram_interactions", website_clicks: "instagram_website_clicks", profile_views: "instagram_profile_views", followers: "instagram_followers" }).map(([key, column]) => [key, persisted.filter(row => row[column as keyof typeof row] != null).length]));
        const daily = (options?.snapshot?.daily || model.daily).filter((row) => row.metric_date >= safePeriod.start && row.metric_date <= safePeriod.end).filter((row) =>
          row.instagram_impressions != null || row.instagram_reach != null || row.instagram_interactions != null ||
          row.instagram_website_clicks != null || row.instagram_profile_views != null || row.instagram_followers != null
        ).map((row) => ({ date: row.metric_date,
          available_metrics: Object.entries({ impressions: "instagram_impressions", reach: "instagram_reach", total_interactions: "instagram_interactions", website_clicks: "instagram_website_clicks", profile_views: "instagram_profile_views", followers: "instagram_followers" }).filter(([, column]) => row[column as keyof typeof row] != null).map(([key]) => key),
          impressions: Number(row.instagram_impressions || 0), reach: Number(row.instagram_reach || 0),
          total_interactions: Number(row.instagram_interactions || 0), website_clicks: Number(row.instagram_website_clicks || 0),
          profile_views: Number(row.instagram_profile_views || 0), accounts_engaged: 0, followers: Number(row.instagram_followers || 0) }));
        const sum = (key: keyof (typeof daily)[number]) => daily.reduce((total, row) => total + Number(row[key] || 0), 0);
        const source = (options?.snapshot?.sources || model.sources).find((item) => item.provider === "instagram");
        const totals = { impressions: sum("impressions"), reach: sum("reach"), total_interactions: sum("total_interactions"), website_clicks: sum("website_clicks"), profile_views: sum("profile_views"), accounts_engaged: 0 };
        const dash: DashboardResponse = { ok: true, client_id: activeClientId, days: daily.length, start: safePeriod.start, end: safePeriod.end,
          daily, period_totals: { ...totals, followers_growth: daily.length > 1 ? daily.at(-1)!.followers - daily[0].followers : 0, followers_current: daily.at(-1)?.followers || 0 },
          totals_last_days: totals, followers_growth_last_days: 0, monthly_totals: totals, last_month_totals: totals,
          monthly_followers_growth: 0, last_month_followers_growth: 0,
          monthly_growth_percent: { impressions:0,reach:0,total_interactions:0,website_clicks:0,profile_views:0,accounts_engaged:0,followers:0 },
          metric_coverage,
          coverage: { covered_days: daily.length, expected_days: Math.round((Date.parse(safePeriod.end) - Date.parse(safePeriod.start)) / 86400000) + 1, missing_days: Math.max(0, Math.round((Date.parse(safePeriod.end) - Date.parse(safePeriod.start)) / 86400000) + 1 - daily.length), is_partial: daily.length < Math.round((Date.parse(safePeriod.end) - Date.parse(safePeriod.start)) / 86400000) + 1 },
          data_available: daily.length > 0, last_sync_at: source?.last_success_at || null };
        if (reqId !== requestRef.current) return;
        writeDashboardCache<DashboardResponse>(dashCacheKey, dash, 180_000);
        startTransition(() => {
          setData((previous) => ({ ...previous, dash }));
        });
        markSectionSuccess("dash");
      } catch (error) {
        if (isAbortError(error) || reqId !== requestRef.current) return;
        markSectionDone("dash", getErrorMessage(error, "Erro ao carregar visão geral"));
      }
    };

    const loadSecondaryTasks = async () => {
      const tasks: Promise<void>[] = [];
      if (!onlyStories) {
        tasks.push(
          (async () => {
          try {
            const cached = options?.force ? null : readDashboardCache<IgMediaItem[]>(mediaCacheKey);
            if (cached) {
              setData(previous => ({ ...previous, media: cached }));
              markSectionSuccess("media");
              return;
            }
            const media: IgMediaItem[] = [];
            const offsets = new Set<number>();
            let offset = 0;
            for (let page = 0; ; page++) {
              if (page >= 200 || offsets.has(offset)) throw new Error("Paginação de publicações incompleta.");
              offsets.add(offset);
              const loadMedia = () => getMedia({ start: safePeriod.start, end: safePeriod.end }, {
                limit: 120, offset, clientId: activeClientId,
                connectionId: resolvedConnectionId, signal: options?.force ? controller.signal : undefined,
              });
              const response = options?.force ? await loadMedia() : await readOnce(`${mediaCacheKey}|offset=${offset}|limit=120`, loadMedia);
              if (reqId !== requestRef.current) return;
              const items = arrayOrEmpty<IgMediaItem>(response.media);
              media.push(...items);
              if (!response.has_more) break;
              if (!items.length) throw new Error("Paginação de publicações incompleta.");
              offset = response.next_offset ?? offset + items.length;
            }
            writeDashboardCache<IgMediaItem[]>(mediaCacheKey, media, 180_000);
            startTransition(() => {
              setData((previous) => ({ ...previous, media }));
            });
            markSectionSuccess("media");
          } catch (error) {
            if (isAbortError(error) || reqId !== requestRef.current) return;
            markSectionDone("media", getErrorMessage(error, "Erro ao carregar mídias"));
          }
          })()
        );
        if (commentsEnabled) tasks.push(
          (async () => {
          try {
            const cached = options?.force ? null : readDashboardCache<{ comments: CommentItem[]; commentsTotal?: number; topWords: TopWord[] }>(commentsCacheKey);
            if (cached) {
              setData(previous => ({ ...previous, comments: cached.comments, commentsTotal: cached.commentsTotal ?? cached.comments.length, topWords: cached.topWords }));
              markSectionSuccess("comments");
              return;
            }
            const loadComments = () => getComments(
              {
                start: safePeriod.start,
                end: safePeriod.end,
              },
              {
                limit: 120,
                offset: 0,
                includeMediaLinked: true,
                clientId: activeClientId,
                connectionId: resolvedConnectionId,
                signal: options?.force ? controller.signal : undefined,
              }
            );
            const commentsResponse = options?.force ? await loadComments() : await readOnce(`${commentsCacheKey}|offset=0|limit=120|linked=1`, loadComments);
            if (reqId !== requestRef.current) return;
            const comments = arrayOrEmpty<CommentItem>(commentsResponse.comments);
            const commentsTotal =
              typeof commentsResponse.total === "number"
                ? Math.max(commentsResponse.total, comments.length)
                : comments.length;
            const topWords = arrayOrEmpty<TopWord>(commentsResponse.top_words);
            writeDashboardCache(commentsCacheKey, { comments, commentsTotal, topWords }, 180_000);
            startTransition(() => {
              setData((previous) => ({
                ...previous,
                comments,
                commentsTotal,
                topWords,
              }));
            });
            markSectionSuccess("comments");
          } catch (error) {
            if (isAbortError(error) || reqId !== requestRef.current) return;
            markSectionDone("comments", getErrorMessage(error, "Erro ao carregar comentários"));
          }
          })()
        );
      } else {
        markSectionDone("media", null);
        markSectionDone("comments", null);
      }
      if (includeStories) {
        tasks.push(
          (async () => {
          try {
            const storiesResponse = await getStories(
              {
                start: safePeriod.start,
                end: safePeriod.end,
              },
              {
                limit: 25,
                connectionId: resolvedConnectionId,
                signal: controller.signal,
              }
            );
            if (reqId !== requestRef.current) return;
            const stories = arrayOrEmpty<StoryItem>(storiesResponse.stories);
            const storiesAvailable = storiesResponse.available !== false;
            const storiesMessage =
              typeof storiesResponse.message === "string" && storiesResponse.message.trim()
                ? storiesResponse.message
                : null;
            writeDashboardCache<StoriesCachePayload>(
              storiesCacheKey,
              {
                stories,
                available: storiesAvailable,
                message: storiesMessage,
              },
              180_000
            );
            startTransition(() => {
              setData((previous) => ({
                ...previous,
                stories,
                storiesAvailable,
                storiesMessage,
              }));
            });
            markSectionSuccess("stories");
          } catch (error) {
            if (isAbortError(error) || reqId !== requestRef.current) return;
            markSectionDone("stories", getErrorMessage(error, "Erro ao carregar stories"));
          }
          })()
        );
      } else {
        markSectionDone("stories", null);
      }
      await Promise.all(tasks);
    };

    try {
      if (!secondaryOnly) {
        await loadDash();
      }
      if (reqId !== requestRef.current) return dataRef.current;
      if (!includeSecondary) {
        setSectionLoading((previous) => ({
          ...previous,
          media: false,
          comments: false,
          stories: false,
        }));
        setSectionRefreshing((previous) => ({
          ...previous,
          media: false,
          comments: false,
          stories: false,
        }));
        return dataRef.current;
      }
      await loadSecondaryTasks();
    } finally {
      if (reqId === requestRef.current) {
        const firstError =
          encounteredErrors.dash ||
          encounteredErrors.media ||
          encounteredErrors.comments ||
          encounteredErrors.stories;
        setSummaryError(firstError || null);
        setLoadingSummary(false);
        setRefreshingSummary(false);
      }
    }

    return Object.values(encounteredErrors).some(Boolean) ? null : dataRef.current;
  }, [
    activeClientId,
    autoLoadStories,
    commentsCacheKey,
    commentsEnabled,
    dashCacheKey,
    isAuthenticated,
    mediaCacheKey,
    model.daily,
    model.sources,
    resolvedConnectionId,
    safePeriod.end,
    safePeriod.start,
    storiesCacheKey,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !activeClientId || model.loading) return;
    const requestKey = dashCacheKey;
    if (autoPrimaryKeyRef.current === requestKey) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      autoPrimaryKeyRef.current = requestKey;
      void reloadSummary({ includeSecondary: false });
    });
    return () => {
      cancelled = true;
    };
  }, [
    activeClientId,
    autoLoadStories,
    dashCacheKey,
    isAuthenticated,
    reloadSummary,
    model.loading,
  ]);

  // Leitura nunca dispara sincronização automaticamente. Dado "stale" é
  // apenas exibido como tal; atualizar é ação explícita do usuário,
  // orquestrada por src/app/syncOrchestrator.ts.

  useEffect(() => {
    if (!secondaryEnabled || !isAuthenticated || !activeClientId) return;
    const requestKey = `${dashCacheKey}|stories=${autoLoadStories ? 1 : 0}|comments=${commentsEnabled ? 1 : 0}`;
    if (autoSecondaryKeyRef.current === requestKey) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      autoSecondaryKeyRef.current = requestKey;
      void reloadSummary({ includeSecondary: true, secondaryOnly: true });
    });
    return () => { cancelled = true; };
  }, [
    activeClientId,
    autoLoadStories,
    commentsEnabled,
    dashCacheKey,
    isAuthenticated,
    reloadSummary,
    resolvedConnectionId,
    secondaryEnabled,
  ]);

  useEffect(() => () => { requestRef.current += 1; abortRef.current?.abort(); }, []);

  return {
    data,
    loadingSummary,
    refreshingSummary,
    sectionLoading,
    sectionRefreshing,
    sectionErrors,
    sectionUpdatedAt,
    summaryError,
    reloadSummary,
  };
}
