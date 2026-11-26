// CRM Supabase Edge Function: dados-whatsapp-templates
// Server-to-server only. Uses the SAME verified Meta secret as the existing MugôZap,
// but NEVER returns it to Mugô Dados or the browser.
// Deployment and org mapping are separate, explicitly approved production steps.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const respond = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const error = (code: string, status: number, message = code) =>
  respond({ ok: false, code, message }, status);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const slug = /^[a-z0-9][a-z0-9_-]{0,63}$/i;
const templateName = /^[a-z][a-z0-9_]{2,80}$/;
const variable = /\{\{(\d+)\}\}/g;

Deno.serve(async (request: Request) => {
  if (!["GET", "POST"].includes(request.method)) return error("METHOD_NOT_ALLOWED", 405);
  const expected = Deno.env.get("DADOS_OPS_API_KEY") || "";
  if (!expected || request.headers.get("X-Dados-Ops-Key") !== expected)
    return error("UNAUTHORIZED", 401);
  const externalId = new URL(request.url).searchParams.get("external_client_id") || "";
  if (!slug.test(externalId)) return error("INVALID_TENANT", 400);

  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const serviceRole = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRole) return error("CRM_NOT_CONFIGURED", 503);
  const admin = createClient(supabaseUrl, serviceRole, { auth: { persistSession: false } });
  try {
    // Organization-owned WABA: explicit mapping only. A CRM integration with client_id
    // grants access only to a client-specific connection, never the agency WABA.
    const orgLink = await admin.from("mugo_dados_whatsapp_org_links")
      .select("organization_id").eq("external_client_id", externalId)
      .eq("status", "active").maybeSingle();
    if (orgLink.error) return error("ORG_LINK_SCHEMA_NOT_READY", 503);
    let organizationId = String(orgLink.data?.organization_id || "");
    let crmClientId: string | null = null;
    if (!organizationId) {
      const link = await admin.from("external_integrations")
        .select("organization_id,client_id")
        .eq("provider", "mugo_dados").eq("external_client_id", externalId)
        .eq("status", "active").maybeSingle();
      if (link.error) return error("LINK_LOOKUP_FAILED", 503);
      if (!link.data?.organization_id || !link.data.client_id) return error("UNKNOWN_EXTERNAL_CLIENT", 403);
      organizationId = String(link.data.organization_id);
      crmClientId = String(link.data.client_id);
    }
    if (!uuid.test(organizationId)) return error("INVALID_ORGANIZATION", 403);
    let connectionQuery = admin.from("whatsapp_connections")
      .select("id,waba_id,credential_reference")
      .eq("organization_id", organizationId).eq("provider", "meta_cloud_api")
      .eq("status", "active");
    connectionQuery = crmClientId ? connectionQuery.eq("client_id", crmClientId)
      : connectionQuery.is("client_id", null);
    const connections = await connectionQuery.limit(2);
    if (connections.error) return error("CONNECTION_LOOKUP_FAILED", 503);
    if (connections.data?.length !== 1) return error("WABA_NOT_LINKED", 409);
    const connection = connections.data[0];
    const wabaId = String(connection.waba_id || "");
    // Only env-backed legacy CRM credentials are supported by this bridge.
    // Other credential references must be implemented with an audited secret resolver.
    if (connection.credential_reference !== "env://legacy-default"
      || wabaId !== Deno.env.get("WABA_ID") || !/^\d+$/.test(wabaId))
      return error("WABA_CREDENTIAL_MISMATCH", 409);
    const token = Deno.env.get("META_ACCESS_TOKEN") || "";
    const version = Deno.env.get("GRAPH_API_VERSION") || "";
    if (!token || !/^v\d+\.\d+$/.test(version)) return error("META_NOT_CONFIGURED", 503);

    if (request.method === "GET" && new URL(request.url).searchParams.get("mode") === "status")
      return respond({ ok: true, data: { connected: true, provider: "mugozap_crm",
        templates_supported: true } });

    const replyWorkerKey = Deno.env.get("TASK_COMMAND_WORKER_KEY") || "";
    const replyMemberId = Deno.env.get("DADOS_WHATSAPP_REPLY_TEAM_MEMBER_ID") || "";
    const anonKey = Deno.env.get("SUPABASE_ANON_KEY") || "";
    const replyEnabled = Boolean(orgLink.data && replyWorkerKey && uuid.test(replyMemberId) && anonKey);

    // Read CRM-owned conversations with the SAME explicit tenant-to-org and
    // CRM connection checks used above for templates. No token leaves CRM.
    const mode = new URL(request.url).searchParams.get("mode") || "";
    const connectionId = String(connection.id);
    if (request.method === "POST" && mode === "reply") {
      if (!replyEnabled) return error("REPLY_UNSUPPORTED", 409);
      const input = await request.json().catch(() => null);
      const conversationId = String(input?.conversation_id || "");
      const message = typeof input?.text === "string" ? input.text.trim() : "";
      const sendId = String(input?.request_id || "");
      if (!uuid.test(conversationId) || !uuid.test(sendId) || !message || message.length > 4000)
        return error("INVALID_REPLY", 422);
      const member = await admin.from("team_members").select("id")
        .eq("id", replyMemberId).eq("organization_id", organizationId).eq("active", true).maybeSingle();
      if (member.error) return error("REPLY_CHECK_FAILED", 503);
      if (!member.data) return error("REPLY_UNSUPPORTED", 409);
      const owned = await admin.from("whatsapp_conversations").select("wa_id,service_window_expires_at")
        .eq("id", conversationId).eq("organization_id", organizationId).eq("connection_id", connectionId).maybeSingle();
      if (owned.error) return error("CONVERSATION_LOOKUP_FAILED", 503);
      if (!owned.data) return error("CONVERSATION_NOT_FOUND", 404);
      const expiresAt = Date.parse(owned.data.service_window_expires_at || "");
      if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) return error("OUTSIDE_WINDOW", 409);

      try {
        const response = await fetch(supabaseUrl + "/functions/v1/mugozap-api", {
          method: "POST",
          headers: { Authorization: "Bearer " + anonKey, apikey: anonKey,
            "Content-Type": "application/json", "X-Task-Command-Worker-Key": replyWorkerKey },
          body: JSON.stringify({ operation: "send_manual_message", payload: {
            team_member_id: replyMemberId, conversationId, waId: owned.data.wa_id, text: message,
            idempotencyKey: "dados-reply-" + conversationId + "-" + sendId,
          } }),
          signal: AbortSignal.timeout(35000),
        });
        const result = await response.json();
        if (response.ok && result?.ok && result.data?.provider_message_id)
          return respond({ ok: true, data: { status: "accepted" } });
        if (result?.code === "SERVICE_WINDOW_CLOSED") return error("OUTSIDE_WINDOW", 409);
        if (result?.code === "CONVERSATION_NOT_FOUND") return error("CONVERSATION_NOT_FOUND", 404);
        if (response.status >= 500 || ["SEND_OUTCOME_UNKNOWN", "MESSAGE_PERSISTENCE_UNCONFIRMED"].includes(result?.code))
          return error("SEND_OUTCOME_UNKNOWN", 502);
        return error("SEND_FAILED", 502);
      } catch {
        return error("SEND_OUTCOME_UNKNOWN", 502);
      }
    }
    if (request.method === "GET" && ["conversations", "messages", "leads"].includes(mode)) {
      if (mode === "messages") {
        const conversationId = String(new URL(request.url).searchParams.get("conversation_id") || "");
        if (!uuid.test(conversationId)) return error("INVALID_CONVERSATION", 422);
        const owned = await admin.from("whatsapp_conversations").select("id")
          .eq("id", conversationId).eq("organization_id", organizationId)
          .eq("connection_id", connectionId).maybeSingle();
        if (owned.error) return error("CONVERSATION_LOOKUP_FAILED", 503);
        if (!owned.data) return error("CONVERSATION_NOT_FOUND", 404);
        const messages = await admin.from("whatsapp_messages")
          .select("id,direction,message_type,status,text_content,template_name,created_at,read_at,failed_at,error_code")
          .eq("organization_id", organizationId).eq("connection_id", connectionId)
          .eq("conversation_id", conversationId)
          .order("created_at", { ascending: false }).limit(200);
        if (messages.error) return error("MESSAGE_QUERY_FAILED", 503);
        return respond({ ok: true, data: { messages: (messages.data || []).reverse().map((m: any) => ({
          id: m.id, direction: m.direction === "in" ? "inbound" : "outbound",
          type: m.message_type || "text", status: m.status || null,
          text: m.text_content || null, template_name: m.template_name || null,
          at: m.created_at, read_at: m.read_at || null,
          failed: Boolean(m.failed_at || m.status === "failed"), error_code: m.error_code || null,
        })) } });
      }
      if (mode === "leads") {
        const start = String(new URL(request.url).searchParams.get("period_start") || "");
        const end = String(new URL(request.url).searchParams.get("period_end") || "");
        if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)
          || start > end) return error("INVALID_PERIOD", 422);
        const rows = await admin.from("whatsapp_conversations")
          .select("id,created_at").eq("organization_id", organizationId)
          .eq("connection_id", connectionId)
          .gte("created_at", start + "T00:00:00Z").lte("created_at", end + "T23:59:59Z")
          .order("created_at", { ascending: false }).limit(500);
        if (rows.error) return error("LEADS_QUERY_FAILED", 503);
        return respond({ ok: true, data: {
          connected: true, truncated: (rows.data || []).length >= 500,
          // No reliable attribution on this bridge; don't invent campaign metrics.
          leads: (rows.data || []).map((c: any) => ({
            id: c.id, first_seen_at: c.created_at, origin: { source: "unknown" },
          })),
        } });
      }
      const requested = Number(new URL(request.url).searchParams.get("limit") || "60");
      const limit = Math.max(1, Math.min(Number.isFinite(requested) ? requested : 60, 200));
      const rows = await admin.from("whatsapp_conversations")
        .select("id,contact_id,status,attendance_mode,unread_count,last_message_at,service_window_expires_at,created_at,wa_id")
        .eq("organization_id", organizationId).eq("connection_id", connectionId)
        .order("last_message_at", { ascending: false, nullsFirst: false }).limit(limit);
      if (rows.error) return error("CONVERSATIONS_QUERY_FAILED", 503);
      const conversations = rows.data || [];
      const contactIds = [...new Set(conversations.map((c: any) => c.contact_id).filter(Boolean))];
      const ids = conversations.map((c: any) => c.id);
      const contacts = contactIds.length
        ? await admin.from("whatsapp_contacts")
          .select("id,display_name,profile_name,first_seen_at,wa_id")
          .eq("organization_id", organizationId).eq("connection_id", connectionId)
          .in("id", contactIds)
        : { data: [], error: null };
      if (contacts.error) return error("CONTACTS_QUERY_FAILED", 503);
      const recent = ids.length
        ? await admin.from("whatsapp_messages")
          .select("conversation_id,direction,text_content,template_name,created_at")
          .eq("organization_id", organizationId).eq("connection_id", connectionId)
          .in("conversation_id", ids).order("created_at", { ascending: false }).limit(1000)
        : { data: [], error: null };
      if (recent.error) return error("PREVIEWS_QUERY_FAILED", 503);
      const byContact = new Map((contacts.data || []).map((c: any) => [c.id, c]));
      const latest = new Map();
      for (const msg of recent.data || []) if (!latest.has(msg.conversation_id))
        latest.set(msg.conversation_id, msg);
      const mask = (value: unknown) => {
        const digits = String(value || "").replace(/\D/g, "");
        return digits ? "•••• " + digits.slice(-4) : "Número protegido";
      };
      return respond({ ok: true, data: {
        connected: true,
        reply_enabled: replyEnabled,
        conversations: conversations.map((c: any) => {
          const contact: any = byContact.get(c.contact_id) || {};
          const msg = latest.get(c.id);
          return {
            id: c.id, status: c.status, attendance_mode: c.attendance_mode,
            unread_count: c.unread_count || 0,
            last_message_at: c.last_message_at, service_window_expires_at: c.service_window_expires_at,
            contact: {
              name: String(contact.display_name || contact.profile_name || "") || null,
              phone_masked: mask(contact.wa_id || c.wa_id),
              first_seen_at: contact.first_seen_at || c.created_at,
            },
            origin: { source: "unknown", ad_headline: null, entry_code: null, at: c.created_at },
            insight: null,
            last_message: msg ? {
              direction: msg.direction, at: msg.created_at,
              text: String(msg.text_content || (msg.template_name ? "Modelo: " + msg.template_name : "Mensagem")).slice(0,600),
            } : null,
          };
        }),
      } });
    }
    const url = `https://graph.facebook.com/${version}/${wabaId}/message_templates`;
    const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
    if (request.method === "GET") {
      const templates: unknown[] = [];
      let next: string | null = url +
        "?fields=id,name,language,status,category,components&limit=100";
      for (let page = 0; page < 5 && next; page++) {
        const response = await fetch(next, { headers, signal: AbortSignal.timeout(12000) });
        if (!response.ok) return error(response.status === 401 ? "META_TOKEN_INVALID"
          : response.status === 403 ? "META_PERMISSION_MISSING" : "META_TEMPLATES_FAILED", 502);
        const data = await response.json();
        templates.push(...(Array.isArray(data.data) ? data.data : []));
        // Only follow a genuine Meta Graph API pagination URL.
        const candidate = String(data.paging?.next || "");
        next = candidate.startsWith(`https://graph.facebook.com/${version}/`) ? candidate : null;
      }
      return respond({ ok: true, data: { templates } });
    }

    // A POST without a mode creates a model for Meta review.
    const input: any = await request.json().catch(() => null);
    const name = String(input?.name || "");
    const category = String(input?.category || "");
    const language = String(input?.language || "");
    const components = input?.components;
    if (!templateName.test(name) || !["MARKETING", "UTILITY"].includes(category)
      || !["pt_BR", "en_US", "es_ES"].includes(language)
      || !Array.isArray(components) || components.length < 1 || components.length > 2)
      return error("INVALID_TEMPLATE", 422, "Modelo inválido.");
    const body = components.find((c: any) => c?.type === "BODY");
    const footer = components.find((c: any) => c?.type === "FOOTER");
    if (!body || typeof body.text !== "string" || body.text.length < 1 || body.text.length > 1024
      || (footer && (typeof footer.text !== "string" || footer.text.length > 60))
      || components.some((c: any) => c?.type !== "BODY" && c?.type !== "FOOTER"))
      return error("INVALID_COMPONENTS", 422, "Confira o texto do modelo.");
    const used = [...body.text.matchAll(variable)].map((match: RegExpMatchArray) => Number(match[1]));
    const cleaned = body.text.replace(variable, "");
    if (cleaned.includes("{{") || cleaned.includes("}}")) return error("INVALID_VARIABLES", 422);
    const max = Math.max(0, ...used);
    if (max > 5 || [...new Set(used)].sort().join(",") !==
       Array.from({ length: max }, (_, i) => i + 1).join(","))
      return error("INVALID_VARIABLES", 422);
    if (max && (!Array.isArray(body.example?.body_text)
       || !Array.isArray(body.example.body_text[0])
       || body.example.body_text[0].length !== max
       || body.example.body_text[0].some((value: unknown) =>
          typeof value !== "string" || value.length > 100 || !value.trim())))
      return error("MISSING_VARIABLE_EXAMPLES", 422);
    const response = await fetch(url, {
      method: "POST", headers,
      body: JSON.stringify({ name, category, language, allow_category_change: true, components }),
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) return error(response.status === 401 ? "META_TOKEN_INVALID"
      : response.status === 403 ? "META_PERMISSION_MISSING"
      : response.status === 400 ? "META_TEMPLATE_REJECTED" : "META_TEMPLATE_CREATE_FAILED", 502);
    const result = await response.json();
    console.log(JSON.stringify({ event: "crm_template_submitted", organization_id: organizationId,
      external_client_id: externalId, template_id: String(result.id || "").slice(0,80) }));
    return respond({ ok: true, data: { template: {
      id: String(result.id || ""), name, language, category: String(result.category || category),
      status: String(result.status || "PENDING"),
    } } }, 201);
  } catch (ex) {
    console.log(JSON.stringify({ event: "crm_templates_failed",
      type: String((ex as Error)?.name || "unknown").slice(0, 50) }));
    return error("TEMPLATE_BRIDGE_FAILED", 503);
  }
});
