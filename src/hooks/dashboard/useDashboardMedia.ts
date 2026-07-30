import { useCallback, useMemo, useRef, useState } from "react";
import { getMedia } from "../../app/api";
import type { IgMediaItem } from "../../app/types";
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

const INITIAL_MEDIA_LIMIT = 120;
type MediaCachePayload = {
  media: IgMediaItem[];
  hasMore: boolean;
  nextOffset: number | null;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

export default function useDashboardMedia({
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
      buildDashboardCacheKey("media", {
        clientId: activeClientId,
        connectionId: activeConnectionId,
        start: safePeriod.start,
        end: safePeriod.end,
        extra: `limit=${INITIAL_MEDIA_LIMIT}`,
      }),
    [activeClientId, activeConnectionId, safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => readDashboardCache<MediaCachePayload>(cacheKey),
    [cacheKey]
  );
  const requestRef = useRef(0);
  const [mediaData, setMediaData] = useState<IgMediaItem[]>(cachedInitial?.media || []);
  const [loadingMedia, setLoadingMedia] = useState(false);
  const [mediaHasMore, setMediaHasMore] = useState(!!cachedInitial?.hasMore);
  const [mediaNextOffset, setMediaNextOffset] = useState<number | null>(
    cachedInitial?.nextOffset ?? 0
  );
  const [mediaError, setMediaError] = useState<string | null>(null);

  const reloadMedia = useCallback(async (
    nextPeriod?: DashboardPeriod | null,
    options?: { force?: boolean }
  ) => {
    if (!isAuthenticated || !activeClientId) return [] as IgMediaItem[];
    const force = !!options?.force;
    if (!force) {
      const cached = readDashboardCache<MediaCachePayload>(cacheKey);
      if (cached) {
        setMediaData(cached.media || []);
        setMediaHasMore(!!cached.hasMore);
        setMediaNextOffset(cached.nextOffset ?? 0);
        return cached.media || [];
      }
    }
    const resolvedPeriod = ensureDashboardPeriod(nextPeriod || safePeriod);

    const reqId = ++requestRef.current;
    setLoadingMedia(true);
    setMediaError(null);
    try {
      const response = await getMedia({
        start: resolvedPeriod.start,
        end: resolvedPeriod.end,
      }, {
        limit: INITIAL_MEDIA_LIMIT,
        offset: 0,
        connectionId: activeConnectionId,
      });
      if (reqId !== requestRef.current) return [] as IgMediaItem[];
      const nextMedia = response.media || [];
      setMediaData(nextMedia);
      setMediaHasMore(!!response.has_more);
      const fallbackOffset = nextMedia.length || 0;
      setMediaNextOffset(
        typeof response.next_offset === "number" ? response.next_offset : fallbackOffset
      );
      writeDashboardCache<MediaCachePayload>(
        cacheKey,
        {
          media: nextMedia,
          hasMore: !!response.has_more,
          nextOffset:
            typeof response.next_offset === "number" ? response.next_offset : fallbackOffset,
        },
        180_000
      );
      return nextMedia;
    } catch (error: unknown) {
      if (reqId !== requestRef.current) return [] as IgMediaItem[];
      setMediaError(errorMessage(error, "Erro ao carregar mídia"));
      return [] as IgMediaItem[];
    } finally {
      if (reqId === requestRef.current) {
        setLoadingMedia(false);
      }
    }
  }, [activeClientId, activeConnectionId, cacheKey, isAuthenticated, safePeriod]);

  const loadMoreMedia = useCallback(async (nextPeriod?: DashboardPeriod | null) => {
    if (!isAuthenticated || !activeClientId) return [] as IgMediaItem[];
    if (loadingMedia || !mediaHasMore) return [] as IgMediaItem[];
    const resolvedPeriod = ensureDashboardPeriod(nextPeriod || safePeriod);
    const offset = Math.max(0, mediaNextOffset || 0);

    const reqId = ++requestRef.current;
    setLoadingMedia(true);
    setMediaError(null);
    try {
      const response = await getMedia(
        {
          start: resolvedPeriod.start,
          end: resolvedPeriod.end,
        },
        {
          limit: INITIAL_MEDIA_LIMIT,
          offset,
          connectionId: activeConnectionId,
        }
      );
      if (reqId !== requestRef.current) return [] as IgMediaItem[];
      const batch = response.media || [];
      setMediaData((prev) => {
        const byId = new Map<string, IgMediaItem>();
        for (const item of prev) byId.set(item.id, item);
        for (const item of batch) byId.set(item.id, item);
        return Array.from(byId.values());
      });
      setMediaHasMore(!!response.has_more);
      const fallbackOffset = offset + batch.length;
      setMediaNextOffset(
        typeof response.next_offset === "number" ? response.next_offset : fallbackOffset
      );
      writeDashboardCache<MediaCachePayload>(
        cacheKey,
        {
          media: Array.from(
            (() => {
              const byId = new Map<string, IgMediaItem>();
              for (const item of mediaData) byId.set(item.id, item);
              for (const item of batch) byId.set(item.id, item);
              return byId.values();
            })()
          ),
          hasMore: !!response.has_more,
          nextOffset:
            typeof response.next_offset === "number" ? response.next_offset : fallbackOffset,
        },
        180_000
      );
      return batch;
    } catch (error: unknown) {
      if (reqId !== requestRef.current) return [] as IgMediaItem[];
      setMediaError(errorMessage(error, "Erro ao carregar mais mídias"));
      return [] as IgMediaItem[];
    } finally {
      if (reqId === requestRef.current) {
        setLoadingMedia(false);
      }
    }
  }, [
    activeClientId,
    activeConnectionId,
    cacheKey,
    isAuthenticated,
    loadingMedia,
    mediaHasMore,
    mediaNextOffset,
    mediaData,
    safePeriod,
  ]);

  return {
    mediaData,
    setMediaData,
    loadingMedia,
    mediaHasMore,
    mediaError,
    loadMoreMedia,
    reloadMedia,
  };
}
