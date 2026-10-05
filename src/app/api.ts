

import type {
  RefreshAllResponse,
  DashboardResponse,
  DashboardDailyRow,
  DashboardPeriodTotals,
  DashboardTotals,
  ClientConnectionsResponse,
  ClientIntegrationsResponse,
  MetaDiscoverAssetsResponse,
  MetaOauthStartResponse,
  CommentsResponse,
  NotesResponse,
  NoteItem,
  Ga4CampaignRow,
  Ga4ChannelRow,
  Ga4CommerceJourney,
  Ga4CollectionResponse,
  Ga4EventGroup,
  Ga4EventGroupItem,
  Ga4EventRow,
  Ga4ReportResponse,
  FbitsOrdersResponse,
  FbitsOrdersSummaryResponse,
  ShopifyCustomersResponse,
  ShopifyReportResponse,
  ExecutiveDashboardResponse,
  StoriesResponse,
  MediaResponse,
  MediaMonthlyResponse,
  MonthsResponse,
  PaidDashboardResponse,
  CampaignsListResponse,
} from "./types";
import type { Period } from "./PeriodContext";
import type {
  CustomerDetailResponse,
  CustomerListResponse,
  IntelligenceAnalysisRecord,
  IntelligenceMessage,
  IntelligenceSnapshot,
} from "./intelligenceTypes";
import { getSupabaseBootstrapError, isLocalAuthEnabled, supabase } from "./supabase";
import {
  clearTenantBrowserState,
  getActiveClientConfigurationWarning,
  getActiveClientId,
} from "./activeClient";
import { getSelectedPeriodRange } from "./periodRange";
import { resolveCatalogConnection, resolveCommerceConnection } from "./connectionManager";
import { getSelectedConnectionId, setSelectedConnectionId } from "./connectionState";

const rawApiBase = String(import.meta.env.VITE_API_BASE || "").trim();
const productionApiBase = "https://api.dados.mugoagencia.com.br";

function resolveApiBase(): string {
  if (!rawApiBase) {
    // Em dev, usa proxy do Vite para evitar CORS.
    return import.meta.env.DEV ? "" : productionApiBase;
  }

  if (import.meta.env.DEV) {
    try {
      const parsed = new URL(rawApiBase);
      const isLocalApi =
        (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1") &&
        (parsed.port === "8000" || parsed.port === "");
      if (isLocalApi) return "";
    } catch {
      // fallback para valor explícito
    }
  }

  return rawApiBase;
}

const API_BASE = resolveApiBase();
const inFlightRouteReads = new Map<string, Promise<unknown>>();

function dedupeInFlight<T>(key: string, load: () => Promise<T>): Promise<T> {
  const existing = inFlightRouteReads.get(key);
  if (existing) return existing as Promise<T>;
  const pending = load().finally(() => {
    if (inFlightRouteReads.get(key) === pending) inFlightRouteReads.delete(key);
  });
  inFlightRouteReads.set(key, pending);
  return pending;
}

type JsonRecord = Record<string, unknown>;
type PeriodQueryInput = Partial<Period> & { days?: number; month?: string };
type RequestSignalOptions = {
  signal?: AbortSignal;
};
type HttpRequestInit = RequestInit & {
  timeoutMs?: number;
};
type ClientRequestOptions = RequestSignalOptions & {
  clientId?: string | null;
};

export class ApiError extends Error {
  status: number;
  code: string;
  retryable: boolean;
  requestId: string;

  constructor(message: string, options: { status: number; code?: string; retryable?: boolean; requestId?: string }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code || "API_ERROR";
    this.retryable = options.retryable ?? (options.status === 429 || options.status >= 500);
    this.requestId = options.requestId || "";
  }
}

export type ClientMembership = {
  client_id: string;
  name: string;
  role?: string | null;
  created_at?: string | null;
};

export type ApiVersion = {
  commit_sha: string;
  build_time: string;
  environment: string;
};

export async function getApiVersion(): Promise<ApiVersion> {
  return http<ApiVersion>("/api/version");
}

export type ClientsResponse = {
  ok: boolean;
  clients: ClientMembership[];
};

export type PlatformCompany = {
  id: string;
  name: string;
  trade_name?: string | null;
  cnpj?: string | null;
  responsible_email?: string | null;
  status: string;
  invitation_status?: string | null;
  created_at?: string | null;
};

export function isUsableGoogleConnection(
  connection: GenericConnection,
  provider: "ga4" | "google_ads",
  activeClientId: string
): boolean {
  const status = String(connection.status || "").toLowerCase();
  return connection.client_id === activeClientId &&
    connection.provider === provider &&
    ["connected", "selection_required"].includes(status) &&
    !connection.disconnected_at &&
    connection.token_available !== false;
}

export function selectUsableGoogleConnection(
  connections: GenericConnection[],
  provider: "ga4" | "google_ads",
  activeClientId: string,
  requestedConnectionId?: string | null
): GenericConnection | null {
  return resolveCatalogConnection(connections, {
    clientId: activeClientId, provider, requestedConnectionId, requireToken: true,
  });
}

export function isUsableMetaConnection(connection: GenericConnection, activeClientId: string): boolean {
  const status = String(connection.status || "").toLowerCase();
  return connection.client_id === activeClientId &&
    connection.provider === "meta" &&
    ["connected", "selection_required"].includes(status) &&
    !connection.disconnected_at &&
    connection.token_available !== false;
}

export function selectUsableMetaConnection(
  connections: GenericConnection[], activeClientId: string, requestedConnectionId?: string | null
): GenericConnection | null {
  return resolveCatalogConnection(connections, {
    clientId: activeClientId, provider: "meta", requestedConnectionId, requireToken: true,
  });
}

export function shouldClearTenantStateOnUnauthorized(status: number, code: string): boolean {
  return status === 401 && (!code || code === "AUTHENTICATION_REQUIRED");
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" ? (value as JsonRecord) : {};
}

export function normalizeApiErrorPayload(payload: unknown, headerRequestId = "") {
  const root = asRecord(payload);
  const detail = asRecord(root.detail);
  const error = asRecord(root.error);
  return {
    message:
      asString(detail.message) ||
      (typeof root.detail === "string" ? root.detail : "") ||
      asString(root.message) ||
      asString(error.message),
    code: asString(detail.code) || asString(root.code) || asString(error.code),
    requestId: asString(detail.request_id) || asString(root.request_id) || headerRequestId,
    retryable:
      typeof detail.retryable === "boolean"
        ? detail.retryable
        : typeof root.retryable === "boolean"
          ? root.retryable
          : undefined,
  };
}

function asNumber(value: unknown, fallback = 0): number {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (value == null) return fallback;
  return String(value);
}

function parseDateInput(value: string): Date | null {
  const text = String(value || "").trim();
  if (!text) return null;
  const parsed = new Date(`${text}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function periodDaysFromRange(start: string, end: string, fallback: number): number {
  const startDate = parseDateInput(start);
  const endDate = parseDateInput(end);
  if (!startDate || !endDate) return fallback;
  const diff = endDate.getTime() - startDate.getTime();
  if (!Number.isFinite(diff) || diff < 0) return fallback;
  return Math.max(1, Math.floor(diff / 86_400_000) + 1);
}

function positiveInt(value: unknown, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.max(1, Math.floor(n));
}

function buildPeriodParams(input: number | PeriodQueryInput | undefined, defaultDays: number): string {
  const params = new URLSearchParams();

  if (typeof input === "number") {
    params.set("days", String(positiveInt(input, defaultDays)));
    return params.toString();
  }

  const period = input || {};
  const selectedRange =
    period.start && period.end ? getSelectedPeriodRange(period) : null;
  const start = asString(selectedRange?.start || period.start).trim();
  const end = asString(selectedRange?.end || period.end).trim();
  const month = asString(period.month).trim();
  const days = positiveInt(period.days, defaultDays);

  const hasRange = Boolean(start && end);

  if (hasRange) {
    params.set("start", start);
    params.set("end", end);
    params.set("days", String(days));
    return params.toString();
  }

  if (month) {
    params.set("month", month);
    params.set("days", String(days));
    return params.toString();
  }

  params.set("days", String(days));
  return params.toString();
}

function pathWithPeriod(path: string, input: number | PeriodQueryInput | undefined, defaultDays: number): string {
  return pathWithClientId(`${path}?${buildPeriodParams(input, defaultDays)}`, getActiveClientId());
}

function pathWithPeriodAndExtras(
  path: string,
  input: number | PeriodQueryInput | undefined,
  defaultDays: number,
  extras?: Record<string, string | number | boolean | null | undefined>
): string {
  const params = new URLSearchParams(buildPeriodParams(input, defaultDays));
  for (const [key, value] of Object.entries(extras || {})) {
    if (value === null || typeof value === "undefined") continue;
    if (typeof value === "string" && !value.trim()) continue;
    params.set(key, String(value));
  }
  if (!params.has("client_id")) params.set("client_id", getActiveClientId());
  return `${path}?${params.toString()}`;
}

function pathWithClientId(path: string, clientId?: string | null): string {
  const cid = asString(clientId).trim();
  if (!cid) return path;

  const [base, query = ""] = path.split("?", 2);
  const params = new URLSearchParams(query);
  params.set("client_id", cid);
  return `${base}?${params.toString()}`;
}

let cachedAccessToken: string | null | undefined;

export function setApiAccessToken(token: string | null | undefined): void {
  cachedAccessToken = token;
}

async function getAccessToken(): Promise<string | null> {
  if (isLocalAuthEnabled()) return null;
  if (cachedAccessToken !== undefined) return cachedAccessToken;
  if (!supabase) {
    throw new Error(
      getSupabaseBootstrapError() ||
        "Supabase Auth nao esta configurado no frontend."
    );
  }
  const { data } = await supabase.auth.getSession();
  cachedAccessToken = data.session?.access_token ?? null;
  return cachedAccessToken;
}

function toHeaders(init?: HeadersInit): Headers {
  const h = new Headers();

  if (!init) return h;

  if (init instanceof Headers) {
    init.forEach((v, k) => h.set(k, v));
    return h;
  }

  if (Array.isArray(init)) {
    for (const [k, v] of init) h.set(k, v);
    return h;
  }

  for (const [k, v] of Object.entries(init)) {
    if (typeof v !== "undefined") h.set(k, String(v));
  }
  return h;
}

const inFlightGets = new Map<string, Promise<unknown>>();

async function executeHttp<T>(path: string, init: HttpRequestInit = {}): Promise<T> {
  const safePath = path.split("?", 1)[0];
  const token = await getAccessToken();
  if (!token && !isLocalAuthEnabled()) {
    throw new Error("Sessão expirada. Faça login novamente.");
  }

  const headers = toHeaders(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const activeClientId = getActiveClientId();
  if (activeClientId) headers.set("X-Client-Id", activeClientId);

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort("timeout"), init.timeoutMs ?? 25_000);
  const originalSignal = init.signal;
  const abortFromCaller = () => controller.abort(originalSignal?.reason);
  originalSignal?.addEventListener("abort", abortFromCaller, { once: true });

  let res: Response;
  try {
    const fetchInit = { ...init };
    delete fetchInit.timeoutMs;
    res = await fetch(`${API_BASE}${path}`, {
      ...fetchInit,
      headers,
      signal: controller.signal,
    });
  } catch (error: unknown) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    const warning = getActiveClientConfigurationWarning();
    throw new ApiError(
      [warning, "Não foi possível acessar os dados agora. Tente novamente em alguns instantes."]
        .filter(Boolean)
        .join(" "),
      { status: 0, code: controller.signal.aborted ? "REQUEST_TIMEOUT" : "NETWORK_ERROR", retryable: true }
    );
  } finally {
    window.clearTimeout(timeoutId);
    originalSignal?.removeEventListener("abort", abortFromCaller);
  }

  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    let detail = "";
    let code = "";
    let retryable = res.status === 429 || res.status >= 500;
    let requestId = res.headers.get("X-Request-ID") || "";
    try {
      const j = txt ? (JSON.parse(txt) as JsonRecord) : null;
      const normalized = normalizeApiErrorPayload(j, requestId);
      detail = normalized.message;
      code = normalized.code;
      requestId = normalized.requestId;
      if (typeof normalized.retryable === "boolean") retryable = normalized.retryable;
      console.warn("[api]", {
        path: safePath,
        status: res.status,
        detail: detail || txt || null,
      });
    } catch {
      console.warn("[api]", {
        path: safePath,
        status: res.status,
        detail: txt || null,
      });
    }
    if (shouldClearTenantStateOnUnauthorized(res.status, code)) {
      clearTenantBrowserState();
      await supabase?.auth.signOut().catch(() => undefined);
    }
    throw new ApiError(
      res.status === 401 && shouldClearTenantStateOnUnauthorized(res.status, code)
        ? "Sua sessão precisa ser renovada."
        : res.status === 403
          ? detail || "Você não tem acesso a esta empresa."
          : res.status === 404
            ? detail || "O recurso solicitado não foi encontrado."
            : res.status === 429
              ? "Muitas solicitações. Aguarde um momento e tente novamente."
              : detail || "Não foi possível carregar os dados agora.",
      { status: res.status, code: code || `HTTP_${res.status}`, retryable, requestId }
    );
  }

  if (res.status === 204) return {} as T;
  return (await res.json()) as T;
}

function http<T>(path: string, init: HttpRequestInit = {}): Promise<T> {
  const method = String(init.method || "GET").toUpperCase();
  if (method !== "GET") return executeHttp<T>(path, init);

  const key = `${getActiveClientId() || ""}:${path}`;
  const existing = inFlightGets.get(key);
  if (existing) return existing as Promise<T>;

  // A caller may stop observing a GET, but an identical consumer can still
  // reuse the same backend work. The shared request owns only its timeout.
  const sharedInit = { ...init };
  delete sharedInit.signal;
  const request = executeHttp<T>(path, sharedInit).finally(() => {
    if (inFlightGets.get(key) === request) inFlightGets.delete(key);
  });
  inFlightGets.set(key, request);
  return request;
}

export async function listClients(): Promise<ClientsResponse> {
  return http<ClientsResponse>("/api/clients");
}

export async function getPlatformProfile(): Promise<{ ok: boolean; is_platform_admin: boolean }> {
  return http("/api/platform/me");
}

export async function listPlatformCompanies(): Promise<{ ok: boolean; companies: PlatformCompany[] }> {
  return http("/api/platform/companies");
}

export async function createPlatformCompany(payload: {
  name: string;
  trade_name?: string;
  cnpj?: string;
  responsible_email: string;
  /** Chave de idempotência por tentativa: reenviada em retries para nunca duplicar a empresa. */
  idempotency_key: string;
}): Promise<{
  ok: boolean;
  company: PlatformCompany;
  responsible_account_exists?: boolean;
  idempotent_replay?: boolean;
}> {
  return http("/api/platform/companies", { method: "POST", body: JSON.stringify(payload) });
}

export async function openPlatformCompany(clientId: string): Promise<{ ok: boolean; company: PlatformCompany }> {
  return http(`/api/platform/companies/${encodeURIComponent(clientId)}/access`, { method: "POST" });
}

export async function createCompanyActivationLink(clientId: string): Promise<{
  ok: true;
  invitation: { id: string; email: string; client_id: string; role: string; expires_at: string | null };
  activation_url: string;
  account_exists: boolean;
}> {
  return http(`/api/platform/companies/${encodeURIComponent(clientId)}/activation-link`, { method: "POST" });
}

export type PendingInvitation = {
  id: string;
  client_id: string;
  role: string;
  company_name: string;
  expires_at: string | null;
};

export async function getMyPendingInvitations(): Promise<{ ok: true; invitations: PendingInvitation[] }> {
  return http("/api/invitations/mine");
}

export async function acceptInvitation(
  invitationId: string
): Promise<{ ok: true; client_id: string | null; role: string | null }> {
  return http(`/api/invitations/${encodeURIComponent(invitationId)}/accept`, { method: "POST" });
}

export async function updatePlatformCompany(
  clientId: string,
  payload: Partial<Pick<PlatformCompany, "name" | "trade_name" | "cnpj" | "status">>
): Promise<{ ok: boolean; company: PlatformCompany }> {
  return http(`/api/platform/companies/${encodeURIComponent(clientId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deletePlatformCompany(
  clientId: string,
  confirmationName: string,
): Promise<{ ok: true; deleted_client_id: string; deleted_company_name: string }> {
  return http(`/api/platform/companies/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmation_name: confirmationName }),
  });
}

/** Acesso de usuário na empresa ativa. Nenhuma senha trafega de volta. */
export type ClientAccessItem = {
  membership_id: string;
  user_id: string;
  email: string | null;
  name: string | null;
  role: string;
  role_label: string;
  is_global_role: boolean;
  email_confirmed: boolean | null;
  last_sign_in_at: string | null;
  created_at: string | null;
};

export type ClientAccessListResponse = {
  ok: true;
  client_id: string;
  items: ClientAccessItem[];
};

/** Empresa resolvida pelo contexto autorizado: nenhum client_id é enviado. */
export async function listClientAccess(
  options?: RequestSignalOptions
): Promise<ClientAccessListResponse> {
  return http("/api/client-access", { signal: options?.signal });
}

export async function createClientAccess(input: {
  name: string;
  email: string;
  password: string;
  password_confirmation: string;
  role: "viewer" | "client_admin";
}): Promise<JsonRecord> {
  return http("/api/client-access", { method: "POST", body: JSON.stringify(input) });
}

export async function resetClientAccessPassword(
  userId: string,
  input: { password: string; password_confirmation: string }
): Promise<JsonRecord> {
  return http(`/api/client-access/${encodeURIComponent(userId)}/password`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function removeClientAccess(userId: string): Promise<JsonRecord> {
  return http(`/api/client-access/${encodeURIComponent(userId)}`, { method: "DELETE" });
}

/** Campos do contexto estratégico da empresa, iguais ao schema do backend. */
export type BusinessContextFields = {
  segment: string | null;
  product_description: string | null;
  audience: string | null;
  positioning: string | null;
  differentiators: string | null;
  commercial_context: string | null;
  goals: string | null;
  strategic_notes: string | null;
};

export type BusinessContextResponse = {
  ok: true;
  client_id: string;
  available: boolean;
  context: BusinessContextFields;
  updated_at?: string | null;
};

/** Empresa ativa resolvida pelo contexto autorizado: nenhum client_id é enviado. */
export async function getBusinessContext(
  options?: RequestSignalOptions
): Promise<BusinessContextResponse> {
  return http("/api/intelligence/business-context", { signal: options?.signal });
}

export async function saveBusinessContext(
  context: Partial<BusinessContextFields>
): Promise<BusinessContextResponse> {
  return http("/api/intelligence/business-context", {
    method: "PUT",
    body: JSON.stringify(context),
  });
}

export async function getIntelligenceContext(
  period: Period,
  options?: RequestSignalOptions,
): Promise<{ ok: true; snapshot: IntelligenceSnapshot }> {
  return http(pathWithPeriod("/api/intelligence/context", period, 30), {
    signal: options?.signal,
  });
}

export async function getLatestIntelligenceAnalysis(
  period: Period,
  options?: RequestSignalOptions,
): Promise<{
  ok: true;
  provider_configured: boolean;
  analysis: IntelligenceAnalysisRecord | null;
}> {
  return http(pathWithPeriod("/api/intelligence/latest", period, 30), {
    signal: options?.signal,
  });
}

export async function generateIntelligenceAnalysis(
  period: Period,
  options?: RequestSignalOptions,
): Promise<{
  ok: true;
  provider_configured: boolean;
  status: string;
  snapshot: IntelligenceSnapshot;
  analysis: IntelligenceAnalysisRecord;
}> {
  return http("/api/intelligence/analyses", {
    method: "POST",
    body: JSON.stringify(period),
    signal: options?.signal,
    timeoutMs: 100_000,
  });
}

export async function getIntelligenceHistory(
  limit = 20,
  options?: RequestSignalOptions,
): Promise<{ ok: true; items: IntelligenceAnalysisRecord[] }> {
  return http(`/api/intelligence/history?limit=${Math.max(1, Math.min(limit, 100))}`, {
    signal: options?.signal,
  });
}

export async function askIntelligence(payload: {
  question: string;
  conversation_id?: string | null;
  start: string;
  end: string;
}, options?: RequestSignalOptions): Promise<{
  ok: true;
  conversation_id: string;
  user_message: IntelligenceMessage;
  assistant_message: IntelligenceMessage;
  snapshot: IntelligenceSnapshot;
}> {
  return http("/api/intelligence/ask", {
    method: "POST",
    body: JSON.stringify(payload),
    signal: options?.signal,
    timeoutMs: 100_000,
  });
}

export async function getIntelligenceMessages(
  conversationId: string,
  options?: RequestSignalOptions,
): Promise<{ ok: true; messages: IntelligenceMessage[] }> {
  return http(
    `/api/intelligence/conversations/${encodeURIComponent(conversationId)}/messages`,
    { signal: options?.signal },
  );
}

export async function createClientInvitation(payload: {
  client_id: string;
  email: string;
  role: "owner" | "agency_admin" | "client_admin" | "viewer";
}): Promise<{ ok: true; invitation: { id: string; email: string; role: string; account_exists?: boolean } }> {
  return http("/api/invitations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

function mapTotals(raw: unknown): DashboardTotals {
  const r = asRecord(raw);
  return {
    impressions: asNumber(r.impressions),
    reach: asNumber(r.reach),
    total_interactions: asNumber(r.total_interactions ?? r.interactions),
    website_clicks: asNumber(r.website_clicks ?? r.website_clicks_day),
    profile_views: asNumber(r.profile_views),
    accounts_engaged: asNumber(r.accounts_engaged),
  };
}

function mapPeriodTotals(raw: unknown): DashboardPeriodTotals {
  const r = asRecord(raw);
  return {
    impressions: asNumber(r.impressions),
    reach: asNumber(r.reach),
    total_interactions: asNumber(r.total_interactions ?? r.interactions),
    website_clicks: asNumber(r.website_clicks ?? r.website_clicks_day),
    profile_views: asNumber(r.profile_views),
    accounts_engaged: asNumber(r.accounts_engaged),
    followers_growth: asNumber(r.followers_growth),
    followers_current: asNumber(r.followers_current ?? r.followers_count),
  };
}

function mapDailyRows(rawRows: unknown[]): DashboardDailyRow[] {
  return rawRows.map((row) => {
    const r = asRecord(row);
    return {
      date: asString(r.date),
      start: asString(r.start),
      end: asString(r.end),
      impressions: asNumber(r.impressions),
      reach: asNumber(r.reach),
      total_interactions: asNumber(r.total_interactions ?? r.interactions),
      website_clicks: asNumber(r.website_clicks ?? r.website_clicks_day),
      profile_views: asNumber(r.profile_views),
      accounts_engaged: asNumber(r.accounts_engaged),
      followers: asNumber(r.followers ?? r.followers_count),
    };
  });
}

function normalizeDashboard(raw: unknown, days: number): DashboardResponse {
  const d = asRecord(raw);
  const dailyRaw = Array.isArray(d.daily) ? d.daily : [];
  const daily = mapDailyRows(dailyRaw);
  const seriesRaw = asRecord(d.series);
  const series = {
    daily: mapDailyRows(
      Array.isArray(seriesRaw.daily) ? (seriesRaw.daily as unknown[]) : dailyRaw
    ),
    weekly: mapDailyRows(
      Array.isArray(seriesRaw.weekly) ? (seriesRaw.weekly as unknown[]) : []
    ),
    monthly: mapDailyRows(
      Array.isArray(seriesRaw.monthly) ? (seriesRaw.monthly as unknown[]) : []
    ),
  };
  const resolvedDaily = daily.length ? daily : series.daily;

  const growthRaw = asRecord(d.monthly_growth_percent);
  const periodGrowthRaw = asRecord(d.period_growth_percent);
  const periodTotalsRaw = asRecord(d.period_totals);
  const periodPreviousTotalsRaw = asRecord(d.period_previous_totals);
  const coverageRaw = asRecord(d.coverage);
  const start = asString(d.start);
  const end = asString(d.end);
  const resolvedDays = asNumber(d.days, periodDaysFromRange(start, end, days));
  const hasPeriodTotals = Object.keys(periodTotalsRaw).length > 0;
  const hasPreviousPeriodTotals = Object.keys(periodPreviousTotalsRaw).length > 0;
  const periodTotals = hasPeriodTotals
    ? mapPeriodTotals(periodTotalsRaw)
    : {
        ...mapTotals(d.totals_last_days),
        followers_growth: asNumber(d.followers_growth_last_days),
      };
  const periodPreviousTotals = hasPreviousPeriodTotals
    ? mapPeriodTotals(periodPreviousTotalsRaw)
    : {
        ...mapTotals(d.totals_previous_period),
        followers_growth: asNumber(d.followers_growth_previous_period),
      };

  return {
    ok: !!d.ok,
    client_id: asString(d.client_id),
    days: resolvedDays,
    start,
    end,
    daily: resolvedDaily,
    series,
    period_totals: periodTotals,
    period_previous_totals: periodPreviousTotals,
    totals_last_days: mapTotals(periodTotals),
    followers_growth_last_days: asNumber(periodTotals.followers_growth),
    totals_previous_period: mapTotals(periodPreviousTotals),
    followers_growth_previous_period: asNumber(periodPreviousTotals.followers_growth),
    period_growth_percent: {
      impressions: asNumber(periodGrowthRaw.impressions),
      reach: asNumber(periodGrowthRaw.reach),
      total_interactions: asNumber(periodGrowthRaw.total_interactions ?? periodGrowthRaw.interactions),
      website_clicks: asNumber(periodGrowthRaw.website_clicks),
      profile_views: asNumber(periodGrowthRaw.profile_views),
      accounts_engaged: asNumber(periodGrowthRaw.accounts_engaged),
      followers: asNumber(periodGrowthRaw.followers),
    },
    monthly_totals: mapTotals(d.monthly_totals),
    last_month_totals: mapTotals(d.last_month_totals),
    monthly_followers_growth: asNumber(d.monthly_followers_growth),
    last_month_followers_growth: asNumber(d.last_month_followers_growth),
    monthly_growth_percent: {
      impressions: asNumber(growthRaw.impressions),
      reach: asNumber(growthRaw.reach),
      total_interactions: asNumber(growthRaw.total_interactions ?? growthRaw.interactions),
      website_clicks: asNumber(growthRaw.website_clicks),
      profile_views: asNumber(growthRaw.profile_views),
      accounts_engaged: asNumber(growthRaw.accounts_engaged),
      followers: asNumber(growthRaw.followers),
    },
    coverage:
      Object.keys(coverageRaw).length > 0
        ? {
            covered_days: asNumber(coverageRaw.covered_days),
            expected_days: asNumber(coverageRaw.expected_days),
            is_partial: Boolean(coverageRaw.is_partial),
            missing_days: asNumber(coverageRaw.missing_days),
          }
        : undefined,
  };
}

function normalizeShopifyReport(raw: unknown): ShopifyReportResponse {
  const report = asRecord(raw);
  const period = asRecord(report.period);
  const summary = asRecord(report.summary);
  const trends = asRecord(report.trends);
  const technical = asRecord(report.technical);
  const coverage = asRecord(report.coverage);

  const daily = Array.isArray(trends.daily) ? trends.daily : [];
  const recentOrders = Array.isArray(report.recent_orders) ? report.recent_orders : [];
  const topProducts = Array.isArray(report.top_products) ? report.top_products : [];
  const recentErrors = Array.isArray(technical.recent_errors) ? technical.recent_errors : [];
  const recentWebhooks = Array.isArray(technical.recent_webhooks) ? technical.recent_webhooks : [];

  return {
    ok: Boolean(report.ok),
    client_id: asString(report.client_id),
    shop_domain: asString(report.shop_domain) || null,
    period: {
      start: asString(period.start),
      end: asString(period.end),
      days: asNumber(period.days, 30),
    },
    coverage: Object.keys(coverage).length ? {
      data_min_in_period: asString(coverage.data_min_in_period) || null,
      data_max_in_period: asString(coverage.data_max_in_period) || null,
      data_max_available: asString(coverage.data_max_available) || null,
      has_data_in_period: Boolean(coverage.has_data_in_period),
    } : undefined,
    summary: {
      revenue_total: asNumber(summary.revenue_total),
      net_revenue: asNumber(summary.net_revenue),
      orders: asNumber(summary.orders),
      average_ticket: asNumber(summary.average_ticket),
      customers: asNumber(summary.customers),
      paid_orders: asNumber(summary.paid_orders),
      cancelled_orders: asNumber(summary.cancelled_orders),
      refunds_count: asNumber(summary.refunds_count),
      refunded_amount: asNumber(summary.refunded_amount),
      refunds_occurred_in_period_count: asNumber(summary.refunds_occurred_in_period_count),
      refunds_occurred_in_period_amount: asNumber(summary.refunds_occurred_in_period_amount),
    },
    trends: {
      daily: daily.map((row) => {
        const item = asRecord(row);
        return {
          date: asString(item.date),
          revenue: asNumber(item.revenue),
          orders: asNumber(item.orders),
          customers: asNumber(item.customers),
          average_ticket: asNumber(item.average_ticket),
        };
      }),
    },
    recent_orders: recentOrders.map((row) => {
      const item = asRecord(row);
      return {
        id: asString(item.id) || null,
        shopify_order_id: asString(item.shopify_order_id),
        order_number: asString(item.order_number) || null,
        name: asString(item.name) || null,
        customer_name: asString(item.customer_name, "Cliente não identificado"),
        customer_email: asString(item.customer_email) || null,
        financial_status: asString(item.financial_status) || null,
        fulfillment_status: asString(item.fulfillment_status) || null,
        total_price: asNumber(item.total_price),
        currency: asString(item.currency, "BRL"),
        created_at_shopify: asString(item.created_at_shopify) || null,
        updated_at_shopify: asString(item.updated_at_shopify) || null,
        items_count: asNumber(item.items_count),
        shop_domain: asString(item.shop_domain) || null,
      };
    }),
    top_products: topProducts.map((row) => {
      const item = asRecord(row);
      return {
        product_id: asString(item.product_id) || null,
        variant_id: asString(item.variant_id) || null,
        title: asString(item.title, "Produto sem título"),
        variant_title: asString(item.variant_title) || null,
        vendor: asString(item.vendor) || null,
        quantity_sold: asNumber(item.quantity_sold),
        revenue: asNumber(item.revenue),
      };
    }),
    technical: {
      last_success_at: asString(technical.last_success_at) || null,
      last_received_at: asString(technical.last_received_at) || null,
      processed_count: asNumber(technical.processed_count),
      error_count: asNumber(technical.error_count),
      recent_errors: recentErrors.map((row) => {
        const item = asRecord(row);
        return {
          id: asString(item.id) || null,
          webhook_id: asString(item.webhook_id) || null,
          topic: asString(item.topic) || null,
          shop_domain: asString(item.shop_domain) || null,
          received_at: asString(item.received_at) || null,
          processed_at: asString(item.processed_at) || null,
          status: asString(item.status) || null,
          error_message: asString(item.error_message) || null,
        };
      }),
      recent_webhooks: recentWebhooks.map((row) => {
        const item = asRecord(row);
        return {
          id: asString(item.id) || null,
          webhook_id: asString(item.webhook_id) || null,
          topic: asString(item.topic) || null,
          shop_domain: asString(item.shop_domain) || null,
          received_at: asString(item.received_at) || null,
          processed_at: asString(item.processed_at) || null,
          status: asString(item.status) || null,
          error_message: asString(item.error_message) || null,
        };
      }),
    },
  };
}

function normalizeShopifyCustomers(raw: unknown): ShopifyCustomersResponse {
  const payload = asRecord(raw);
  const period = asRecord(payload.period);
  const summary = asRecord(payload.summary);
  const topCustomer = asRecord(summary.top_customer);
  const items = Array.isArray(payload.items) ? payload.items : [];

  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    period: {
      start: asString(period.start),
      end: asString(period.end),
      days: asNumber(period.days, 30),
    },
    count: asNumber(payload.count),
    summary: {
      total_customers: asNumber(summary.total_customers),
      recurring_customers: asNumber(summary.recurring_customers),
      multi_order_customers: asNumber(summary.multi_order_customers),
      top_customer: Object.keys(topCustomer).length
        ? {
            name: asString(topCustomer.name) || null,
            email: asString(topCustomer.email) || null,
            total_spent: asNumber(topCustomer.total_spent),
            total_orders: asNumber(topCustomer.total_orders),
            status: asString(topCustomer.status) || null,
          }
        : null,
    },
    items: items.map((row) => {
      const item = asRecord(row);
      return {
        customer_key: asString(item.customer_key),
        shopify_customer_id: asString(item.shopify_customer_id) || null,
        name: asString(item.name, "Cliente não identificado"),
        email: asString(item.email) || null,
        total_orders: asNumber(item.total_orders),
        total_spent: asNumber(item.total_spent),
        average_ticket: asNumber(item.average_ticket),
        last_purchase_at: asString(item.last_purchase_at) || null,
        first_purchase_at: asString(item.first_purchase_at) || null,
        status: asString(item.status, "new"),
        all_time_orders: asNumber(item.all_time_orders),
        shop_domain: asString(item.shop_domain) || null,
      };
    }),
  };
}

function normalizeComments(raw: unknown): CommentsResponse {
  const payload = asRecord(raw);
  const comments = Array.isArray(payload.comments) ? payload.comments : [];
  const topWords = Array.isArray(payload.top_words) ? payload.top_words : [];
  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    connection_id: asString(payload.connection_id) || null,
    days: asNumber(payload.days, 30),
    start: asString(payload.start) || undefined,
    end: asString(payload.end) || undefined,
    limit: asNumber(payload.limit, 120),
    offset: asNumber(payload.offset, 0),
    has_more: Boolean(payload.has_more),
    next_offset: payload.next_offset == null ? null : asNumber(payload.next_offset),
    total: asNumber(payload.total),
    comments: comments.map((row) => {
      const item = asRecord(row);
      return {
        id: asNumber(item.id) || undefined,
        client_id: asString(item.client_id),
        media_id: asString(item.media_id),
        comment_id: asString(item.comment_id),
        text: asString(item.text) || undefined,
        username: asString(item.username) || undefined,
        timestamp: asString(item.timestamp) || undefined,
      };
    }),
    top_words: topWords.map((row) => {
      const item = asRecord(row);
      return {
        word: asString(item.word),
        count: asNumber(item.count),
      };
    }),
  };
}

function normalizeStories(raw: unknown): StoriesResponse {
  const payload = asRecord(raw);
  const stories = Array.isArray(payload.stories) ? payload.stories : [];
  return {
    ok: Boolean(payload.ok),
    available: payload.available === false ? false : true,
    client_id: asString(payload.client_id),
    connection_id: asString(payload.connection_id) || null,
    message: asString(payload.message) || undefined,
    error: asString(payload.error) || null,
    stories: stories.map((row) => {
      const item = asRecord(row);
      return {
        id: asString(item.id),
        media_type: asString(item.media_type) || undefined,
        media_url: asString(item.media_url) || undefined,
        thumbnail_url: asString(item.thumbnail_url) || undefined,
        thumb_url: asString(item.thumb_url) || undefined,
        timestamp: asString(item.timestamp) || undefined,
        permalink: asString(item.permalink) || undefined,
      };
    }),
  };
}

function normalizeMedia(raw: unknown): MediaResponse {
  const payload = asRecord(raw);
  const media = Array.isArray(payload.media) ? payload.media : [];
  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    connection_id: asString(payload.connection_id) || null,
    days: asNumber(payload.days, 365),
    start: asString(payload.start) || undefined,
    end: asString(payload.end) || undefined,
    limit: asNumber(payload.limit, 120),
    offset: asNumber(payload.offset, 0),
    has_more: Boolean(payload.has_more),
    next_offset: payload.next_offset == null ? null : asNumber(payload.next_offset),
    media: media.map((row) => {
      const item = asRecord(row);
      return {
        id: asString(item.id),
        media_type: asString(item.media_type),
        media_product_type: asString(item.media_product_type),
        caption: asString(item.caption) || null,
        timestamp: asString(item.timestamp) || null,
        permalink: asString(item.permalink) || null,
        thumb_url: asString(item.thumb_url) || null,
        thumbnail_url: asString(item.thumbnail_url) || null,
        media_url: asString(item.media_url) || null,
        insights: asRecord(item.insights),
      };
    }),
  };
}

function normalizeMediaMonthly(raw: unknown): MediaMonthlyResponse {
  const payload = asRecord(raw);
  const months = Array.isArray(payload.months) ? payload.months : [];
  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    connection_id: asString(payload.connection_id) || null,
    days: asNumber(payload.days, 3650),
    start: asString(payload.start) || undefined,
    end: asString(payload.end) || undefined,
    months: months.map((row) => {
      const item = asRecord(row);
      return {
        month: asString(item.month),
        posts: asNumber(item.posts),
        reels: asNumber(item.reels),
        reach: asNumber(item.reach),
        views: asNumber(item.views),
        interactions: asNumber(item.interactions),
        profile_visits: asNumber(item.profile_visits),
        likes: asNumber(item.likes),
        comments: asNumber(item.comments),
        shares: asNumber(item.shares),
        saved: asNumber(item.saved),
      };
    }),
  };
}

function normalizeNotes(raw: unknown): NotesResponse {
  const payload = asRecord(raw);
  const notes = Array.isArray(payload.notes) ? payload.notes : [];
  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    connection_id: asString(payload.connection_id) || null,
    limit: asNumber(payload.limit, 80),
    available: payload.available === false ? false : true,
    message: asString(payload.message) || undefined,
    notes: notes.map((row) => {
      const item = asRecord(row);
      return {
        id: asString(item.id),
        client_id: asString(item.client_id),
        title: asString(item.title),
        body: asString(item.body),
        created_at: asString(item.created_at),
        updated_at: asString(item.updated_at),
      };
    }),
  };
}

function normalizeGa4Channels(raw: unknown): Ga4CollectionResponse<Ga4ChannelRow> {
  const payload = asRecord(raw);
  const period = asRecord(payload.period);
  const items = Array.isArray(payload.items) ? payload.items : [];

  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    property_id: asString(payload.property_id),
    period: {
      start: asString(period.start),
      end: asString(period.end),
      days: asNumber(period.days, 30),
    },
    count: asNumber(payload.count),
    items: items.map((row) => {
      const item = asRecord(row);
      return {
        source_medium: asString(item.source_medium),
        source: asString(item.source) || null,
        medium: asString(item.medium) || null,
        sessions: asNumber(item.sessions),
        active_users: asNumber(item.active_users),
        total_users: asNumber(item.total_users),
        event_count: asNumber(item.event_count),
        ecommerce_purchases: asNumber(item.ecommerce_purchases),
        purchase_revenue: asNumber(item.purchase_revenue),
        total_revenue: asNumber(item.total_revenue),
      };
    }),
  };
}

function normalizeGa4Campaigns(raw: unknown): Ga4CollectionResponse<Ga4CampaignRow> {
  const payload = asRecord(raw);
  const period = asRecord(payload.period);
  const items = Array.isArray(payload.items) ? payload.items : [];

  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    property_id: asString(payload.property_id),
    period: {
      start: asString(period.start),
      end: asString(period.end),
      days: asNumber(period.days, 30),
    },
    count: asNumber(payload.count),
    items: items.map((row) => {
      const item = asRecord(row);
      return {
        campaign_name: asString(item.campaign_name, "(not set)"),
        source_medium: asString(item.source_medium) || null,
        source: asString(item.source) || null,
        medium: asString(item.medium) || null,
        sessions: asNumber(item.sessions),
        active_users: asNumber(item.active_users),
        total_users: asNumber(item.total_users),
        event_count: asNumber(item.event_count),
        ecommerce_purchases: asNumber(item.ecommerce_purchases),
        purchase_revenue: asNumber(item.purchase_revenue),
        total_revenue: asNumber(item.total_revenue),
      };
    }),
  };
}

function normalizeGa4Events(raw: unknown): Ga4CollectionResponse<Ga4EventRow> {
  const payload = asRecord(raw);
  const period = asRecord(payload.period);
  const items = Array.isArray(payload.items) ? payload.items : [];

  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    property_id: asString(payload.property_id),
    period: {
      start: asString(period.start),
      end: asString(period.end),
      days: asNumber(period.days, 30),
    },
    count: asNumber(payload.count),
    items: items.map((row) => {
      const item = asRecord(row);
      return {
        event_name: asString(item.event_name),
        label: asString(item.label) || null,
        description: asString(item.description) || null,
        event_count: asNumber(item.event_count),
        total_users: asNumber(item.total_users),
        first_seen_at: asString(item.first_seen_at) || null,
        last_seen_at: asString(item.last_seen_at) || null,
      };
    }),
  };
}

function normalizeGa4EventGroupItem(raw: unknown): Ga4EventGroupItem {
  const item = asRecord(raw);
  return {
    event_name: asString(item.event_name),
    label: asString(item.label) || asString(item.event_name),
    description: asString(item.description) || null,
    event_count: asNumber(item.event_count),
    total_users: asNumber(item.total_users),
    first_seen_at: asString(item.first_seen_at) || null,
    last_seen_at: asString(item.last_seen_at) || null,
  };
}

function normalizeGa4EventGroup(raw: unknown): Ga4EventGroup {
  const group = asRecord(raw);
  const items = Array.isArray(group.items) ? group.items : [];
  return {
    key: asString(group.key),
    title: asString(group.title),
    description: asString(group.description),
    total_events: asNumber(group.total_events),
    total_users: asNumber(group.total_users),
    items: items.map(normalizeGa4EventGroupItem),
  };
}

function normalizeGa4CommerceJourney(raw: unknown): Ga4CommerceJourney {
  const payload = asRecord(raw);
  const summary = asRecord(payload.summary);
  const items = Array.isArray(payload.items) ? payload.items : [];
  return {
    summary: {
      view_item: asNumber(summary.view_item),
      add_to_cart: asNumber(summary.add_to_cart),
      begin_checkout: asNumber(summary.begin_checkout),
      add_payment_info: asNumber(summary.add_payment_info),
      purchase: asNumber(summary.purchase),
      add_to_cart_rate: asNumber(summary.add_to_cart_rate),
      checkout_rate: asNumber(summary.checkout_rate),
      payment_info_rate: asNumber(summary.payment_info_rate),
      purchase_rate: asNumber(summary.purchase_rate),
      purchase_rate_from_view_item: asNumber(summary.purchase_rate_from_view_item),
    },
    items: items.map(normalizeGa4EventGroupItem),
  };
}

function normalizeGa4Report(raw: unknown): Ga4ReportResponse {
  const payload = asRecord(raw);
  const period = asRecord(payload.period);
  const summary = asRecord(payload.summary);
  const funnel = asRecord(payload.funnel);
  const trends = asRecord(payload.trends);
  const meta = asRecord(payload.meta);
  const dailyRows = Array.isArray(trends.daily) ? trends.daily : [];

  return {
    ok: Boolean(payload.ok),
    client_id: asString(payload.client_id),
    property_id: asString(payload.property_id),
    period: {
      start: asString(period.start),
      end: asString(period.end),
      days: asNumber(period.days, 30),
    },
    summary: {
      sessions: asNumber(summary.sessions),
      active_users: asNumber(summary.active_users),
      total_users: asNumber(summary.total_users),
      event_count: asNumber(summary.event_count),
      purchases: asNumber(summary.purchases),
      purchase_revenue: asNumber(summary.purchase_revenue),
      total_revenue: asNumber(summary.total_revenue),
      average_daily_active_users: asNumber(summary.average_daily_active_users),
      average_daily_total_users: asNumber(summary.average_daily_total_users),
    },
    funnel: {
      view_item: asNumber(funnel.view_item),
      add_to_cart: asNumber(funnel.add_to_cart),
      begin_checkout: asNumber(funnel.begin_checkout),
      add_payment_info: asNumber(funnel.add_payment_info),
      purchase: asNumber(funnel.purchase),
    },
    commerce_journey: normalizeGa4CommerceJourney(payload.commerce_journey),
    behavior: normalizeGa4EventGroup(payload.behavior),
    engagement: normalizeGa4EventGroup(payload.engagement),
    merchandising: normalizeGa4EventGroup(payload.merchandising),
    trends: {
      daily: dailyRows.map((row) => {
        const item = asRecord(row);
        return {
          date: asString(item.date),
          sessions: asNumber(item.sessions),
          active_users: asNumber(item.active_users),
          total_users: asNumber(item.total_users),
          event_count: asNumber(item.event_count),
          ecommerce_purchases: asNumber(item.ecommerce_purchases),
          purchase_revenue: asNumber(item.purchase_revenue),
          total_revenue: asNumber(item.total_revenue),
          view_item_count: asNumber(item.view_item_count),
          add_to_cart_count: asNumber(item.add_to_cart_count),
          begin_checkout_count: asNumber(item.begin_checkout_count),
          purchase_count: asNumber(item.purchase_count),
        };
      }),
    },
    channels: normalizeGa4Channels({
      ok: payload.ok,
      client_id: payload.client_id,
      property_id: payload.property_id,
      period: payload.period,
      count: Array.isArray(payload.channels) ? payload.channels.length : 0,
      items: payload.channels,
    }).items,
    campaigns: normalizeGa4Campaigns({
      ok: payload.ok,
      client_id: payload.client_id,
      property_id: payload.property_id,
      period: payload.period,
      count: Array.isArray(payload.campaigns) ? payload.campaigns.length : 0,
      items: payload.campaigns,
    }).items,
    events: normalizeGa4Events({
      ok: payload.ok,
      client_id: payload.client_id,
      property_id: payload.property_id,
      period: payload.period,
      count: Array.isArray(payload.events) ? payload.events.length : 0,
      items: payload.events,
    }).items,
    meta: {
      last_synced_at: asString(meta.last_synced_at) || null,
      daily_rows: asNumber(meta.daily_rows),
      channel_rows: asNumber(meta.channel_rows),
      campaign_rows: asNumber(meta.campaign_rows),
      event_rows: asNumber(meta.event_rows),
    },
  };
}

function clientClientPath(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `/api/clients/${encodeURIComponent(getActiveClientId())}${suffix}`;
}

export async function startClientMetaOAuth(): Promise<MetaOauthStartResponse> {
  return http<MetaOauthStartResponse>(
    `/api/oauth/meta/start?client_id=${encodeURIComponent(getActiveClientId())}`
  );
}

export async function startGoogleOAuth(
  product: "ga4" | "google_ads"
): Promise<{ ok: boolean; integration_product: string; authorization_url: string }> {
  const routeProduct = product === "google_ads" ? "ads" : "ga4";
  return http<{ ok: boolean; integration_product: string; authorization_url: string }>(
    `/api/oauth/google/${routeProduct}/start`
  );
}

export async function startShopifyOAuth(
  shopDomain: string
): Promise<{ ok: boolean; authorization_url: string; shop_domain: string }> {
  return http<{ ok: boolean; authorization_url: string; shop_domain: string }>(
    `/api/oauth/shopify/start?shop=${encodeURIComponent(shopDomain)}`
  );
}

export async function selectShopifyConnection(
  connectionId: string
): Promise<JsonRecord> {
  return http(`/api/oauth/shopify/${encodeURIComponent(connectionId)}/select`, {
    method: "POST",
  });
}

export async function syncShopifyConnection(
  connectionId: string,
  days = 30
): Promise<JsonRecord> {
  return http(
    `/api/oauth/shopify/${encodeURIComponent(connectionId)}/sync?days=${positiveInt(days, 30)}`,
    { method: "POST" }
  );
}

export type GenericConnection = {
  id: string;
  client_id: string;
  provider: string;
  status: string;
  disconnected_at?: string | null;
  token_available?: boolean;
  account_id?: string | null;
  account_name?: string | null;
  external_key?: string | null;
  scopes?: string[];
  last_sync_at?: string | null;
  next_sync_at?: string | null;
  historical_start?: string | null;
  historical_end?: string | null;
  last_error?: string | null;
  metadata?: Record<string, unknown>;
  capabilities?: {
    ga4_authorized: boolean;
    ga4_configured: boolean;
    ga4_status: string;
    ads_authorized: boolean;
    ads_configured: boolean;
    ads_status: string;
  };
};

export async function listGenericConnections(): Promise<{
  ok: boolean;
  client_id: string;
  connections: GenericConnection[];
}> {
  return http("/api/connections");
}

export type GoogleGa4Property = {
  account?: string;
  account_name?: string;
  property?: string;
  property_name?: string;
};

export type GoogleGa4Stream = {
  name?: string;
  display_name?: string;
  type?: string;
  web_stream_data?: Record<string, unknown>;
};

export type GoogleAdsAccount = {
  customer_id: string;
  resource_name?: string;
  descriptive_name?: string | null;
  currency_code?: string | null;
  time_zone?: string | null;
  is_manager?: boolean;
  is_test_account?: boolean;
  status?: string | null;
  /** "direct" = acesso direto; "manager" = acessada via conta administradora (MCC). */
  access?: "direct" | "manager";
  login_customer_id?: string | null;
  manager_customer_id?: string | null;
  manager_name?: string | null;
  level?: number;
  /** Código Google ao ler os detalhes DESTA conta (ex.: CUSTOMER_NOT_ENABLED). */
  details_error?: string | null;
  /** Código Google ao listar as contas vinculadas (customer_client) desta MCC. */
  hierarchy_error?: string | null;
  /** Código Google do fallback customer_client_link desta MCC. */
  links_error?: string | null;
};

/** Somente exibição: 1234567890 -> 123-456-7890. */
export function formatGoogleAdsCustomerId(customerId: string | null | undefined): string {
  return String(customerId || "").replace(/(\d{3})(\d{3})(\d{4})/, "$1-$2-$3");
}

/** "Amalie — 123-456-7890" quando há nome; nunca só o ID cru. */
export function formatGoogleAdsAccountLabel(account: GoogleAdsAccount): string {
  const formattedId = account.customer_id.replace(/(\d{3})(\d{3})(\d{4})/, "$1-$2-$3");
  return account.descriptive_name
    ? `${account.descriptive_name} — ${formattedId}`
    : `Conta ${formattedId}`;
}

export async function listGoogleGa4Properties(
  connectionId: string
): Promise<{ ok: boolean; properties: GoogleGa4Property[]; property_count?: number; message?: string | null }> {
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/ga4/properties`);
}

export async function selectGoogleGa4Property(
  connectionId: string,
  propertyId: string,
  details?: { accountId?: string; propertyName?: string; streamId?: string }
): Promise<JsonRecord> {
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/ga4/select`, {
    method: "POST",
    body: JSON.stringify({
      property_id: propertyId,
      account_id: details?.accountId,
      property_name: details?.propertyName,
      stream_id: details?.streamId,
    }),
  });
}

export async function listGoogleGa4Streams(
  connectionId: string,
  propertyId: string
): Promise<{ ok: boolean; streams: GoogleGa4Stream[] }> {
  return http(
    `/api/oauth/google/${encodeURIComponent(connectionId)}/ga4/streams?property_id=${encodeURIComponent(propertyId)}`
  );
}

export async function listGoogleAdsAccounts(
  connection: GenericConnection,
  activeClientId: string
): Promise<{ ok: boolean; configured?: boolean; reason?: string; accounts?: GoogleAdsAccount[] }> {
  if (!isUsableGoogleConnection(connection, "google_ads", activeClientId)) {
    throw new ApiError("A conexão Google Ads não está ativa. Conecte novamente.", {
      status: 409, code: "GOOGLE_CONNECTION_DISCONNECTED",
    });
  }
  return http(`/api/oauth/google/${encodeURIComponent(connection.id)}/ads/accounts`);
}

export async function selectGoogleAdsAccount(
  connectionId: string,
  customerId: string
): Promise<JsonRecord> {
  // Só o customer_id: o backend resolve login-customer-id, nome e tipo pela
  // hierarquia descoberta na listagem desta conexão.
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/ads/select`, {
    method: "POST",
    body: JSON.stringify({ customer_id: customerId }),
  });
}

export async function syncGoogleConnection(connectionId: string): Promise<JsonRecord> {
  return http(`/api/oauth/google/${encodeURIComponent(connectionId)}/sync`, {
    method: "POST",
  });
}

export async function disconnectGenericConnection(
  connection: GenericConnection
): Promise<JsonRecord> {
  const providerPath = connection.provider === "shopify" ? "shopify" : "google";
  return http(`/api/oauth/${providerPath}/${encodeURIComponent(connection.id)}`, {
    method: "DELETE",
  });
}

export async function discoverClientMetaAssets(
  handoff: string
): Promise<MetaDiscoverAssetsResponse> {
  return http<MetaDiscoverAssetsResponse>(
    `/api/oauth/meta/discover-assets?client_id=${encodeURIComponent(getActiveClientId())}&handoff=${encodeURIComponent(handoff)}`
  );
}

export async function discoverPendingClientMetaAssets(handoff: string): Promise<MetaDiscoverAssetsResponse> {
  return http<MetaDiscoverAssetsResponse>(
    `/api/oauth/meta/pending-assets?client_id=${encodeURIComponent(getActiveClientId())}&handoff=${encodeURIComponent(handoff)}`
  );
}

export async function configureExistingMetaOrganic(
  connectionId: string
): Promise<MetaDiscoverAssetsResponse> {
  return http<MetaDiscoverAssetsResponse>(
    `/api/oauth/meta/${encodeURIComponent(connectionId)}/configure-organic`,
    { method: "POST" }
  );
}

/** Relista as contas Meta Ads com a autorização salva (direto + Businesses). */
export async function discoverExistingMetaAdAccounts(
  connectionId: string
): Promise<MetaDiscoverAssetsResponse> {
  return http<MetaDiscoverAssetsResponse>(
    `/api/oauth/meta/${encodeURIComponent(connectionId)}/discover-ad-accounts`,
    { method: "POST" }
  );
}

export type ManualMetaAssetsPayload = {
  page_id?: string;
  instagram_id?: string;
  ad_account_id?: string;
};

export type ManualMetaAssetsValidation = {
  ok: boolean;
  page?: { id?: string; name?: string } | null;
  instagram?: { id?: string; username?: string; name?: string } | null;
  ad_account?: { id?: string; name?: string; account_status?: number } | null;
};

export async function validateManualMetaAssets(
  connectionId: string,
  payload: ManualMetaAssetsPayload
): Promise<ManualMetaAssetsValidation> {
  return http(`/api/oauth/meta/${encodeURIComponent(connectionId)}/manual-assets/validate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function saveManualMetaAssets(
  connectionId: string,
  payload: ManualMetaAssetsPayload
): Promise<JsonRecord> {
  return http(`/api/oauth/meta/${encodeURIComponent(connectionId)}/manual-assets`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type MetaOrganicActivation = {
  ok: boolean;
  authorization_connection_id: string;
  organic_connection_id: string;
  page_id: string;
  instagram_id: string;
  status: string;
  initial_sync: JsonRecord;
  metrics_written: number;
  last_sync_at?: string | null;
  code: string;
  request_id: string;
};

export async function activateMetaOrganic(
  authorizationConnectionId: string,
  payload: { page_id: string; instagram_id: string }
): Promise<MetaOrganicActivation> {
  return http(`/api/oauth/meta/${encodeURIComponent(authorizationConnectionId)}/organic/activate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function linkClientAssets(
  payload: {
    handoff: string;
    business_ids: string[];
    page_ids: string[];
    instagram_ig_user_ids: string[];
    ad_account_ids: string[];
  }
): Promise<JsonRecord> {
  return http<JsonRecord>(clientClientPath("/connections/link-assets"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listClientConnections(): Promise<ClientConnectionsResponse> {
  return http<ClientConnectionsResponse>(clientClientPath("/connections"));
}

/**
 * Contrato canônico consolidado (Fase 3): uma chamada, todas as integrações,
 * com status de autorização + status de sincronização + contas selecionadas.
 * Não substitui listClientConnections/listGenericConnections nesta fase —
 * ver nota de compatibilidade na entrega da Fase 3.
 */
export async function getClientIntegrations(options?: RequestSignalOptions): Promise<ClientIntegrationsResponse> {
  return http<ClientIntegrationsResponse>(clientClientPath("/integrations"), {
    signal: options?.signal,
  });
}

export type MetaAdsSelectableAccount = {
  connection_id: string;
  ad_account_id: string;
  ad_account_name?: string;
  status?: string;
  scopes?: string[];
};

export async function listClientMetaAdsAccounts(): Promise<{ ok: boolean; accounts: MetaAdsSelectableAccount[] }> {
  return http(clientClientPath("/meta-ads/accounts"));
}

export async function selectClientMetaAdsAccount(adAccountId: string): Promise<JsonRecord> {
  return http(clientClientPath("/meta-ads/select"), {
    method: "POST",
    body: JSON.stringify({ ad_account_id: adAccountId }),
  });
}

export async function syncClientMetaAdsAccount(connectionId: string): Promise<JsonRecord> {
  return http(clientClientPath("/meta-ads/sync"), {
    method: "POST",
    // Sem since/until: o backend aplica o período canônico
    // (resolve_period, 30 dias por padrão).
    body: JSON.stringify({ connection_id: connectionId }),
  });
}

export async function disconnectClientConnection(connectionId: string): Promise<JsonRecord> {
  return http<JsonRecord>(clientClientPath(`/connections/${encodeURIComponent(connectionId)}`), {
    method: "DELETE",
  });
}

export async function refreshAll(
  limit = 40,
  options?: { connectionId?: string | null; start?: string; end?: string }
): Promise<RefreshAllResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const connectionId = String(options?.connectionId || "").trim();
  const start = String(options?.start || "").trim();
  const end = String(options?.end || "").trim();
  if (connectionId) params.set("connection_id", connectionId);
  if (start && end) {
    params.set("start", start);
    params.set("end", end);
  }
  return http<RefreshAllResponse>(`/api/ig/sync?${params.toString()}`, { method: "POST" });
}

export async function getDashboard(
  period: number | PeriodQueryInput = 30,
  options?: { connectionId?: string | null } & RequestSignalOptions
): Promise<DashboardResponse> {
  const fallbackDays = typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  const raw = await http<unknown>(
    pathWithPeriodAndExtras("/api/dashboard", period, fallbackDays, {
      connection_id: String(options?.connectionId || "").trim() || null,
    }),
    { signal: options?.signal }
  );
  return normalizeDashboard(raw, fallbackDays);
}

export async function getAiSummary(period: number | PeriodQueryInput = 30): Promise<JsonRecord> {
  return http<JsonRecord>(pathWithPeriod("/api/ai/summary", period, 30), { method: "POST" });
}

export async function getDashboardByMonth(month: string): Promise<DashboardResponse> {
  const raw = await http<unknown>(`/api/dashboard?month=${encodeURIComponent(month)}`);
  return normalizeDashboard(raw, 30);
}

export async function getAiSummaryByMonth(month: string): Promise<JsonRecord> {
  return http<JsonRecord>(`/api/ai/summary?month=${encodeURIComponent(month)}`, { method: "POST" });
}

export async function getComments(
  period: number | PeriodQueryInput = 0,
  options?: {
    limit?: number;
    offset?: number;
    includeMediaLinked?: boolean;
    connectionId?: string | null;
    signal?: AbortSignal;
  }
): Promise<CommentsResponse> {
  const defaultDays = typeof period === "number" ? period : 30;
  const raw = await http<unknown>(
    pathWithPeriodAndExtras("/api/comments", period, defaultDays, {
      limit: options?.limit,
      offset: options?.offset,
      include_media_linked: options?.includeMediaLinked ? "true" : null,
      connection_id: String(options?.connectionId || "").trim() || null,
    }),
    { signal: options?.signal }
  );
  return normalizeComments(raw);
}

export async function getStories(
  period: number | PeriodQueryInput = 30,
  options?: { limit?: number; connectionId?: string | null; signal?: AbortSignal }
): Promise<StoriesResponse> {
  const raw = await http<unknown>(
    pathWithPeriodAndExtras("/api/ig/stories", period, 30, {
      limit: options?.limit,
      connection_id: String(options?.connectionId || "").trim() || null,
    }),
    { signal: options?.signal }
  );
  return normalizeStories(raw);
}

export async function listMonths(): Promise<MonthsResponse> {
  return http<MonthsResponse>(`/api/months`);
}

export async function listMonthsByConnection(
  options?: { connectionId?: string | null }
): Promise<MonthsResponse> {
  const params = new URLSearchParams();
  const connectionId = String(options?.connectionId || "").trim();
  if (connectionId) params.set("connection_id", connectionId);
  const suffix = params.toString();
  return http<MonthsResponse>(`/api/months${suffix ? `?${suffix}` : ""}`);
}

export async function getMedia(
  period: number | PeriodQueryInput = 365,
  options?: { limit?: number; offset?: number; connectionId?: string | null; signal?: AbortSignal }
): Promise<MediaResponse> {
  const fallbackDays = typeof period === "number" ? positiveInt(period, 365) : positiveInt(period.days, 365);
  const raw = await http<unknown>(
    pathWithPeriodAndExtras("/api/media", period, fallbackDays, {
      limit: options?.limit,
      offset: options?.offset,
      connection_id: String(options?.connectionId || "").trim() || null,
    }),
    { signal: options?.signal }
  );
  return normalizeMedia(raw);
}

export async function getMediaMonthly(
  period: number | PeriodQueryInput = 3650,
  options?: { connectionId?: string | null; signal?: AbortSignal }
): Promise<MediaMonthlyResponse> {
  const raw = await http<unknown>(
    pathWithPeriodAndExtras("/api/media/monthly", period, 3650, {
      connection_id: String(options?.connectionId || "").trim() || null,
    }),
    { signal: options?.signal }
  );
  return normalizeMediaMonthly(raw);
}

export async function getDashboardPaid(
  period: number | PeriodQueryInput = 30,
  options?: {
    connectionId?: string | null;
    campaign?: string;
    adset?: string;
    ad?: string;
    platform?: string;
    signal?: AbortSignal;
  }
): Promise<PaidDashboardResponse> {
  return http<PaidDashboardResponse>(
    pathWithPeriodAndExtras("/api/dashboard/paid", period, 30, {
      connection_id: String(options?.connectionId || "").trim() || null,
      campaign: String(options?.campaign || "").trim() || null,
      adset: String(options?.adset || "").trim() || null,
      ad: String(options?.ad || "").trim() || null,
      platform: String(options?.platform || "").trim() || null,
    }),
    { signal: options?.signal }
  );
}

export async function getCampaignsRanking(
  period: number | PeriodQueryInput = 30,
  options?: { connectionId?: string | null; limit?: number; signal?: AbortSignal }
): Promise<CampaignsListResponse> {
  return http<CampaignsListResponse>(
    pathWithPeriodAndExtras("/api/campaigns", period, 30, {
      connection_id: String(options?.connectionId || "").trim() || null,
      limit: String(options?.limit || 8),
    }),
    { signal: options?.signal }
  );
}

export async function getExecutiveDashboard(
  period: number | PeriodQueryInput = 30,
  options?: { signal?: AbortSignal }
): Promise<ExecutiveDashboardResponse> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  return http<ExecutiveDashboardResponse>(
    pathWithPeriodAndExtras("/api/dashboard/executive", period, fallbackDays),
    { signal: options?.signal }
  );
}

// Fonte de verdade da conexão Shopify usada nas leituras é o backend, nunca
// o localStorage isolado: com ponteiro local válido, respeita-o; sem
// ponteiro e com exatamente UMA conexão Shopify ativa, resolve e persiste
// essa (mesmo connection manager canônico usado pelo Ecommerce —
// resolveCommerceConnection); com 0 ou 2+ conexões, segue sem connection_id
// e deixa o backend responder 409 explicitamente (nunca escolhe sozinho
// entre conexões ambíguas).
export async function resolveShopifyConnectionIdForRead(clientId: string): Promise<string | null> {
  const stored = getSelectedConnectionId(clientId, "shopify");
  if (stored) return stored;
  try {
    const { connections } = await listGenericConnections();
    const resolved = resolveCommerceConnection(
      connections.filter((connection) => connection.provider === "shopify"),
      null
    );
    if (resolved?.id) {
      setSelectedConnectionId(clientId, "shopify", resolved.id);
      return resolved.id;
    }
  } catch {
    // Sem lista de conexões disponível agora: segue sem connection_id.
  }
  return null;
}

export async function getShopifyReport(
  period: number | PeriodQueryInput = 30
): Promise<ShopifyReportResponse> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  const path = pathWithPeriod("/api/shopify/report", period, fallbackDays);
  const raw = await dedupeInFlight(
    `shopify-report:${getActiveClientId()}:${path}`,
    () => http<unknown>(path),
  );
  return normalizeShopifyReport(raw);
}

export async function getShopifyCustomers(
  period: number | PeriodQueryInput = 30
): Promise<ShopifyCustomersResponse> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  const path = pathWithPeriod("/api/shopify/customers", period, fallbackDays);
  const raw = await dedupeInFlight(
    `shopify-customers:${getActiveClientId()}:${path}`,
    () => http<unknown>(path),
  );
  return normalizeShopifyCustomers(raw);
}

export async function getFbitsOrdersSummary(
  period: number | PeriodQueryInput = 30
): Promise<FbitsOrdersSummaryResponse> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  return http<FbitsOrdersSummaryResponse>(
    pathWithPeriod("/api/fbits/dashboard", period, fallbackDays)
  );
}

export async function getFbitsOrders(
  period: number | PeriodQueryInput = 30
): Promise<FbitsOrdersResponse> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  return http<FbitsOrdersResponse>(pathWithPeriod("/api/fbits/orders", period, fallbackDays));
}

export async function syncFbits(
  period?: PeriodQueryInput,
  options?: { clientId?: string | null }
): Promise<JsonRecord> {
  const params = new URLSearchParams();
  const start = asString(period?.start).trim();
  const end = asString(period?.end).trim();
  const days = positiveInt(period?.days, 30);
  const clientId = asString(options?.clientId).trim() || getActiveClientId();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (!start || !end) params.set("days", String(days));
  if (clientId) params.set("client_id", clientId);
  return http<JsonRecord>(`/api/fbits/sync?${params.toString()}`, {
    method: "POST",
  });
}

/** Valida o token na FBITS e salva a conexão cifrada da empresa ativa. O token
 * vai só no corpo desta requisição e nunca volta na resposta. */
export async function connectFbits(token: string): Promise<JsonRecord> {
  return http<JsonRecord>(clientClientPath("/fbits/connect"), {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function syncFbitsConnection(): Promise<JsonRecord> {
  return http<JsonRecord>(clientClientPath("/fbits/sync"), { method: "POST" });
}

export async function disconnectFbitsConnection(): Promise<JsonRecord> {
  return http<JsonRecord>(clientClientPath("/fbits/connection"), { method: "DELETE" });
}

export async function getGa4Report(
  period: number | PeriodQueryInput = 30,
  options?: ClientRequestOptions
): Promise<Ga4ReportResponse> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  const raw = await http<unknown>(
    pathWithClientId(pathWithPeriod("/api/google/ga4/report", period, fallbackDays), options?.clientId),
    { signal: options?.signal }
  );
  return normalizeGa4Report(raw);
}

export async function getGa4Channels(
  period: number | PeriodQueryInput = 30,
  options?: ClientRequestOptions
): Promise<Ga4CollectionResponse<Ga4ChannelRow>> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  const raw = await http<unknown>(
    pathWithClientId(pathWithPeriod("/api/google/ga4/channels", period, fallbackDays), options?.clientId),
    { signal: options?.signal }
  );
  return normalizeGa4Channels(raw);
}

export async function getGa4Campaigns(
  period: number | PeriodQueryInput = 30,
  options?: ClientRequestOptions
): Promise<Ga4CollectionResponse<Ga4CampaignRow>> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  const raw = await http<unknown>(
    pathWithClientId(pathWithPeriod("/api/google/ga4/campaigns", period, fallbackDays), options?.clientId),
    { signal: options?.signal }
  );
  return normalizeGa4Campaigns(raw);
}

export async function getGa4Events(
  period: number | PeriodQueryInput = 30,
  options?: ClientRequestOptions
): Promise<Ga4CollectionResponse<Ga4EventRow>> {
  const fallbackDays =
    typeof period === "number" ? positiveInt(period, 30) : positiveInt(period.days, 30);
  const raw = await http<unknown>(
    pathWithClientId(pathWithPeriod("/api/google/ga4/events", period, fallbackDays), options?.clientId),
    { signal: options?.signal }
  );
  return normalizeGa4Events(raw);
}

export async function syncGa4(
  period?: PeriodQueryInput,
  options?: { clientId?: string | null; connectionId?: string | null }
): Promise<JsonRecord> {
  const params = new URLSearchParams();
  const start = String(period?.start || "").trim();
  const end = String(period?.end || "").trim();
  const days = positiveInt(period?.days, 30);
  const clientId = asString(options?.clientId).trim();
  const resolvedClientId = clientId || getActiveClientId();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (!start || !end) params.set("days", String(days));
  if (resolvedClientId) params.set("client_id", resolvedClientId);
  const connectionId = asString(options?.connectionId).trim()
    || getSelectedConnectionId(resolvedClientId, "ga4");
  if (connectionId) params.set("connection_id", connectionId);
  return http<JsonRecord>(`/api/google/ga4/sync?${params.toString()}`, {
    method: "POST",
  });
}

export async function syncAds(
  period?: PeriodQueryInput,
  options?: { connectionId?: string | null; clientId?: string | null }
): Promise<JsonRecord> {
  const resolvedClientId = String(options?.clientId || getActiveClientId()).trim();
  const payload: JsonRecord = {};
  const start = String(period?.start || "").trim();
  const end = String(period?.end || "").trim();
  const connectionId = String(options?.connectionId || "").trim();
  if (resolvedClientId) payload.client_id = resolvedClientId;
  if (start) payload.since = start;
  if (end) payload.until = end;
  if (connectionId) payload.connection_id = connectionId;
  return http<JsonRecord>("/api/ads/sync", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listNotes(options?: { limit?: number; connectionId?: string | null }): Promise<NotesResponse> {
  const params = new URLSearchParams();
  if (typeof options?.limit === "number" && Number.isFinite(options.limit)) {
    params.set("limit", String(Math.max(1, Math.floor(options.limit))));
  }
  const connectionId = String(options?.connectionId || "").trim();
  if (connectionId) params.set("connection_id", connectionId);
  const suffix = params.toString();
  const raw = await http<unknown>(`/api/notes${suffix ? `?${suffix}` : ""}`);
  return normalizeNotes(raw);
}

export async function createNote(payload: { title: string; body: string }): Promise<{ ok: boolean; note: NoteItem }> {
  return http<{ ok: boolean; note: NoteItem }>(`/api/notes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateNote(
  noteId: string,
  payload: { title?: string; body?: string }
): Promise<{ ok: boolean; note: NoteItem }> {
  return http<{ ok: boolean; note: NoteItem }>(`/api/notes/${encodeURIComponent(noteId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/** Base de clientes do tenant atual. O client_id é resolvido no backend. */
export async function getCustomers(
  params: { search?: string; page?: number; pageSize?: number } = {},
  options?: RequestSignalOptions,
): Promise<CustomerListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  const suffix = query.toString();
  return http<CustomerListResponse>(`/api/customers${suffix ? `?${suffix}` : ""}`, {
    signal: options?.signal,
  });
}

export async function getCustomerDetail(
  customerId: string,
  options?: RequestSignalOptions,
): Promise<CustomerDetailResponse> {
  return http<CustomerDetailResponse>(
    `/api/customers/${encodeURIComponent(customerId)}`,
    { signal: options?.signal },
  );
}


/** Refresh por membership: somente provider e período, sem IDs de ativos. */
export async function refreshProviderData(
  provider: "fbits" | "shopify" | "meta" | "google",
  period: { start: string; end: string },
): Promise<{ ok: boolean; client_id: string; provider: string }> {
  return http(clientClientPath(`/data-refresh/${provider}`), {
    method: "POST",
    body: JSON.stringify({ start: period.start, end: period.end }),
  });
}
