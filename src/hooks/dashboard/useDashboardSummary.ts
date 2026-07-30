import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getComments, getDashboard, getMedia, getStories } from "../../app/api";
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
  autoLoadStories?: boolean;
  period?: DashboardPeriod | null;
};

type ReloadOptions = {
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
  autoLoadStories = true,
  period,
}: Params) {
  const safePeriod = useMemo(() => ensureDashboardPeriod(period), [period]);
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
      const cachedComments = resolvedConnectionId
        ? readDashboardCache<{ comments: CommentItem[]; commentsTotal?: number; topWords: TopWord[] }>(commentsCacheKey)
        : null;
      const cachedStoriesRaw = resolvedConnectionId
        ? readDashboardCache<StoryItem[] | StoriesCachePayload>(storiesCacheKey)
        : null;
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
        dash: resolvedConnectionId ? readDashboardCache<DashboardResponse>(dashCacheKey) : null,
        media: resolvedConnectionId
          ? arrayOrEmpty<IgMediaItem>(readDashboardCache<IgMediaItem[]>(mediaCacheKey))
          : [],
        comments: arrayOrEmpty<CommentItem>(cachedComments?.comments),
        commentsTotal:
          typeof cachedComments?.commentsTotal === "number"
            ? cachedComments.commentsTotal
            : arrayOrEmpty<CommentItem>(cachedComments?.comments).length,
        topWords: arrayOrEmpty<TopWord>(cachedComments?.topWords),
        stories: resolvedConnectionId ? cachedStories.stories : [],
        storiesAvailable: resolvedConnectionId
          ? hasCachedStories
            ? cachedStories.available
            : autoLoadStories
          : true,
        storiesMessage: resolvedConnectionId
          ? hasCachedStories
            ? cachedStories.message
            : autoLoadStories
              ? null
              : "Stories ao vivo ficam sob demanda. Use “Tentar novamente” para consultar a API."
          : null,
        paid: null,
      };
    },
    [autoLoadStories, commentsCacheKey, dashCacheKey, mediaCacheKey, resolvedConnectionId, storiesCacheKey]
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

  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  useEffect(() => {
    if (resolvedConnectionId) {
      setData(cachedInitial);
      dataRef.current = cachedInitial;
      setSectionErrors(emptySectionErrors());
      setSummaryError(null);
      return;
    }
    const emptyData: SummaryData = {
      dash: null,
      media: [],
      comments: [],
      commentsTotal: 0,
      topWords: [],
      stories: [],
      storiesAvailable: true,
      storiesMessage: null,
      paid: null,
    };
    setData(emptyData);
    dataRef.current = emptyData;
    setLoadingSummary(false);
    setRefreshingSummary(false);
    setSectionLoading(emptySectionState());
    setSectionRefreshing(emptySectionState());
    setSectionErrors(emptySectionErrors());
    setSectionUpdatedAt(emptyTimestamps());
    setSummaryError(null);
    autoPrimaryKeyRef.current = "";
    autoSecondaryKeyRef.current = "";
  }, [autoLoadStories, cachedInitial, resolvedConnectionId]);

  const reloadSummary = useCallback(async (options?: ReloadOptions) => {
    if (!isAuthenticated || !activeClientId) return null;
    if (!resolvedConnectionId) {
      const emptyData: SummaryData = {
        dash: null,
        media: [],
        comments: [],
        commentsTotal: 0,
        topWords: [],
        stories: [],
        storiesAvailable: true,
        storiesMessage: null,
        paid: null,
      };
      setData(emptyData);
      dataRef.current = emptyData;
      setSummaryError(null);
      setLoadingSummary(false);
      setRefreshingSummary(false);
      setSectionLoading(emptySectionState());
      setSectionRefreshing(emptySectionState());
      setSectionErrors(emptySectionErrors());
      return null;
    }

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
      comments: includeSecondary && !onlyStories && currentData.comments.length === 0,
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
        const dash = await getDashboard(
          {
            start: safePeriod.start,
            end: safePeriod.end,
          },
          {
            connectionId: resolvedConnectionId,
            signal: controller.signal,
          }
        );
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
            const mediaResponse = await getMedia(
              {
                start: safePeriod.start,
                end: safePeriod.end,
              },
              {
                limit: 120,
                offset: 0,
                connectionId: resolvedConnectionId,
                signal: controller.signal,
              }
            );
            if (reqId !== requestRef.current) return;
            const media = arrayOrEmpty<IgMediaItem>(mediaResponse.media);
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
        tasks.push(
          (async () => {
          try {
            const commentsResponse = await getComments(
              {
                start: safePeriod.start,
                end: safePeriod.end,
              },
              {
                limit: 120,
                offset: 0,
                includeMediaLinked: true,
                connectionId: resolvedConnectionId,
                signal: controller.signal,
              }
            );
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

    return dataRef.current;
  }, [
    activeClientId,
    autoLoadStories,
    commentsCacheKey,
    dashCacheKey,
    isAuthenticated,
    mediaCacheKey,
    resolvedConnectionId,
    safePeriod.end,
    safePeriod.start,
    storiesCacheKey,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !activeClientId || !resolvedConnectionId) return;
    const requestKey = dashCacheKey;
    const secondaryRequestKey = `${dashCacheKey}|stories=${autoLoadStories ? 1 : 0}`;
    if (autoPrimaryKeyRef.current === requestKey) return;
    autoPrimaryKeyRef.current = requestKey;
    if (secondaryEnabled) {
      autoSecondaryKeyRef.current = secondaryRequestKey;
    }
    void reloadSummary({ includeSecondary: secondaryEnabled });
    return () => {
      abortRef.current?.abort();
    };
  }, [
    activeClientId,
    autoLoadStories,
    dashCacheKey,
    isAuthenticated,
    reloadSummary,
    resolvedConnectionId,
    secondaryEnabled,
  ]);

  useEffect(() => {
    if (!secondaryEnabled || !isAuthenticated || !activeClientId || !resolvedConnectionId) return;
    const requestKey = `${dashCacheKey}|stories=${autoLoadStories ? 1 : 0}`;
    if (autoSecondaryKeyRef.current === requestKey) return;
    autoSecondaryKeyRef.current = requestKey;
    void reloadSummary({ includeSecondary: true, secondaryOnly: true });
  }, [
    activeClientId,
    autoLoadStories,
    dashCacheKey,
    isAuthenticated,
    reloadSummary,
    resolvedConnectionId,
    secondaryEnabled,
  ]);

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
