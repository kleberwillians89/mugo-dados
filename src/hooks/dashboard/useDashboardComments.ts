import { useCallback, useMemo, useRef, useState } from "react";
import { getComments } from "../../app/api";
import type { CommentItem, TopWord } from "../../app/types";
import { ensureDashboardPeriod, type DashboardPeriod } from "./period";
import {
  buildDashboardCacheKey,
  readDashboardCache,
  writeDashboardCache,
} from "./cache";

type Params = {
  isAuthenticated: boolean;
  activeClientId: string;
  activeConnectionId?: string | null;
  period?: DashboardPeriod | null;
};

const INITIAL_COMMENTS_LIMIT = 120;
type CommentsCachePayload = {
  comments: CommentItem[];
  topWords: TopWord[];
  hasMore: boolean;
  nextOffset: number | null;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

export default function useDashboardComments({
  isAuthenticated,
  activeClientId,
  activeConnectionId,
  period,
}: Params) {
  const safePeriod = useMemo(
    () => ensureDashboardPeriod(period),
    [period]
  );
  const cacheKey = useMemo(
    () =>
      buildDashboardCacheKey("comments", {
        clientId: activeClientId,
        connectionId: activeConnectionId,
        start: safePeriod.start,
        end: safePeriod.end,
        extra: `limit=${INITIAL_COMMENTS_LIMIT}`,
      }),
    [activeClientId, activeConnectionId, safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => readDashboardCache<CommentsCachePayload>(cacheKey),
    [cacheKey]
  );
  const requestRef = useRef(0);
  const [comments, setComments] = useState<CommentItem[]>(cachedInitial?.comments || []);
  const [topWords, setTopWords] = useState<TopWord[]>(cachedInitial?.topWords || []);
  const [loadingComments, setLoadingComments] = useState(false);
  const [commentsHasMore, setCommentsHasMore] = useState(!!cachedInitial?.hasMore);
  const [commentsNextOffset, setCommentsNextOffset] = useState<number | null>(
    cachedInitial?.nextOffset ?? 0
  );
  const [commentsError, setCommentsError] = useState<string | null>(null);

  const reloadComments = useCallback(
    async (
      nextPeriod?: DashboardPeriod | null,
      options?: { includeMediaLinked?: boolean; force?: boolean }
    ) => {
      if (!isAuthenticated || !activeClientId) return;
      const force = !!options?.force;
      if (!force) {
        const cached = readDashboardCache<CommentsCachePayload>(cacheKey);
        if (cached) {
          setComments(cached.comments || []);
          setTopWords(cached.topWords || []);
          setCommentsHasMore(!!cached.hasMore);
          setCommentsNextOffset(cached.nextOffset ?? 0);
          return;
        }
      }
      const resolvedPeriod = ensureDashboardPeriod(nextPeriod || safePeriod);

      const reqId = ++requestRef.current;
      setLoadingComments(true);
      setCommentsError(null);
      try {
        const response = await getComments({
          start: resolvedPeriod.start,
          end: resolvedPeriod.end,
        }, {
          limit: INITIAL_COMMENTS_LIMIT,
          offset: 0,
          includeMediaLinked: !!options?.includeMediaLinked,
          connectionId: activeConnectionId,
        });
        if (reqId !== requestRef.current) return;
        setComments(response.comments || []);
        setTopWords(response.top_words || []);
        setCommentsHasMore(!!response.has_more);
        const fallbackOffset = (response.comments || []).length;
        setCommentsNextOffset(
          typeof response.next_offset === "number" ? response.next_offset : fallbackOffset
        );
        writeDashboardCache<CommentsCachePayload>(
          cacheKey,
          {
            comments: response.comments || [],
            topWords: response.top_words || [],
            hasMore: !!response.has_more,
            nextOffset:
              typeof response.next_offset === "number" ? response.next_offset : fallbackOffset,
          },
          180_000
        );
      } catch (error: unknown) {
        if (reqId !== requestRef.current) return;
        setCommentsError(errorMessage(error, "Erro ao carregar comentários"));
      } finally {
        if (reqId === requestRef.current) {
          setLoadingComments(false);
        }
      }
    },
    [activeClientId, activeConnectionId, cacheKey, isAuthenticated, safePeriod]
  );

  const loadMoreComments = useCallback(async (nextPeriod?: DashboardPeriod | null) => {
    if (!isAuthenticated || !activeClientId) return;
    if (loadingComments || !commentsHasMore) return;
    const resolvedPeriod = ensureDashboardPeriod(nextPeriod || safePeriod);
    const offset = Math.max(0, commentsNextOffset || 0);

    const reqId = ++requestRef.current;
    setLoadingComments(true);
    setCommentsError(null);
    try {
      const response = await getComments(
        {
          start: resolvedPeriod.start,
          end: resolvedPeriod.end,
        },
        {
          limit: INITIAL_COMMENTS_LIMIT,
          offset,
          includeMediaLinked: false,
          connectionId: activeConnectionId,
        }
      );
      if (reqId !== requestRef.current) return;
      const batch = response.comments || [];
      setComments((prev) => {
        const map = new Map<string, CommentItem>();
        for (const item of prev) map.set(item.comment_id, item);
        for (const item of batch) map.set(item.comment_id, item);
        return Array.from(map.values());
      });
      setCommentsHasMore(!!response.has_more);
      const fallbackOffset = offset + batch.length;
      setCommentsNextOffset(
        typeof response.next_offset === "number" ? response.next_offset : fallbackOffset
      );
      writeDashboardCache<CommentsCachePayload>(
        cacheKey,
        {
          comments: Array.from(
            (() => {
              const map = new Map<string, CommentItem>();
              for (const item of comments) map.set(item.comment_id, item);
              for (const item of batch) map.set(item.comment_id, item);
              return map.values();
            })()
          ),
          topWords,
          hasMore: !!response.has_more,
          nextOffset:
            typeof response.next_offset === "number" ? response.next_offset : fallbackOffset,
        },
        180_000
      );
    } catch (error: unknown) {
      if (reqId !== requestRef.current) return;
      setCommentsError(errorMessage(error, "Erro ao carregar mais comentários"));
    } finally {
      if (reqId === requestRef.current) {
        setLoadingComments(false);
      }
    }
  }, [
    activeClientId,
    activeConnectionId,
    cacheKey,
    comments,
    commentsHasMore,
    commentsNextOffset,
    isAuthenticated,
    loadingComments,
    safePeriod,
    topWords,
  ]);

  return {
    comments,
    topWords,
    loadingComments,
    commentsHasMore,
    commentsError,
    loadMoreComments,
    reloadComments,
  };
}
