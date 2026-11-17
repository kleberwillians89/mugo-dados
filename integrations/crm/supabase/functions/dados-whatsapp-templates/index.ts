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

    // This endpoint creates a model for Meta review. It NEVER sends WhatsApp messages.
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
