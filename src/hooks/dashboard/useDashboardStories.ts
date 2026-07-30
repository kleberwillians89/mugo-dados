import { useCallback, useMemo, useRef, useState } from "react";
import { getStories } from "../../app/api";
import type { StoryItem } from "../../app/types";
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

type StoriesCachePayload = {
  stories: StoryItem[];
  available: boolean;
  message: string;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

export default function useDashboardStories({
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
      buildDashboardCacheKey("stories", {
        clientId: activeClientId,
        connectionId: activeConnectionId,
        start: safePeriod.start,
        end: safePeriod.end,
      }),
    [activeClientId, activeConnectionId, safePeriod.end, safePeriod.start]
  );
  const cachedInitial = useMemo(
    () => readDashboardCache<StoriesCachePayload>(cacheKey),
    [cacheKey]
  );
  const requestRef = useRef(0);
  const [stories, setStories] = useState<StoryItem[]>(cachedInitial?.stories || []);
  const [loadingStories, setLoadingStories] = useState(false);
  const [storiesAvailable, setStoriesAvailable] = useState(cachedInitial?.available ?? true);
  const [storiesMessage, setStoriesMessage] = useState(cachedInitial?.message || "");
  const [storiesError, setStoriesError] = useState<string | null>(null);

  const reloadStories = useCallback(async (
    nextPeriod?: DashboardPeriod | null,
    options?: { force?: boolean }
  ) => {
    if (!isAuthenticated || !activeClientId) return;
    const force = !!options?.force;
    if (!force) {
      const cached = readDashboardCache<StoriesCachePayload>(cacheKey);
      if (cached) {
        setStories(cached.stories || []);
        setStoriesAvailable(!!cached.available);
        setStoriesMessage(cached.message || "");
        return;
      }
    }
    const resolvedPeriod = ensureDashboardPeriod(nextPeriod || safePeriod);

    const reqId = ++requestRef.current;
    setLoadingStories(true);
    setStoriesError(null);
    try {
      const response = await getStories(
        {
          start: resolvedPeriod.start,
          end: resolvedPeriod.end,
        },
        {
          connectionId: activeConnectionId,
          limit: 25,
        }
      );
      if (reqId !== requestRef.current) return;
      setStories(response.stories || []);
      setStoriesAvailable(!!response.available);
      setStoriesMessage(response.message || "");
      writeDashboardCache<StoriesCachePayload>(
        cacheKey,
        {
          stories: response.stories || [],
          available: !!response.available,
          message: response.message || "",
        },
        180_000
      );
    } catch (error: unknown) {
      if (reqId !== requestRef.current) return;
      setStoriesError(errorMessage(error, "Erro ao carregar stories"));
    } finally {
      if (reqId === requestRef.current) {
        setLoadingStories(false);
      }
    }
  }, [activeClientId, activeConnectionId, cacheKey, isAuthenticated, safePeriod]);

  return {
    stories,
    loadingStories,
    storiesAvailable,
    storiesMessage,
    storiesError,
    reloadStories,
  };
}
