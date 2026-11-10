// Webhook do Direct do Instagram (app da Mugô no Meta), para todas as marcas com Instagram no MUGOVERSO.
//
// GET: verificação (hub.challenge com IG_WEBHOOK_VERIFY_TOKEN; sem ele, usa WHATSAPP_VERIFY_TOKEN).
// POST: confere a assinatura (X-Hub-Signature-256 com META_APP_SECRET, o segredo do app que faz o login do
// Instagram; sem ele, WHATSAPP_APP_SECRET), descobre a marca pela conta do Instagram e grava cada mensagem.
// Mensagem recebida entra como "pendente"; o eco do que a marca mandou entra como "registrado" (se não foi o
// MUGOVERSO que mandou, é a equipe respondendo pelo app e a IA para naquela conversa).
// Depois de gravar, avisa o backend (IG_DM_HOOK_URL + IG_DM_HOOK_KEY) para responder na hora; sem isso,
// o job de 5 em 5 minutos responde. Banco falhou → 500 para a Meta reenviar (gravação idempotente pelo mid).
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { validSignature } from '../_shared/whatsapp-cloud.ts'
import { dmEvents } from '../_shared/instagram-dm.ts'

const text = (body: string, status = 200) => new Response(body, { status, headers: { 'content-type': 'text/plain' } })

function inBackground(task: Promise<unknown>) {
  const guarded = task.catch((error) => console.error({ event: 'ig_dm_background_failed', message: String(error).slice(0, 200) }))
  const runtime = (globalThis as unknown as { EdgeRuntime?: { waitUntil(p: Promise<unknown>): void } }).EdgeRuntime
  if (runtime?.waitUntil) runtime.waitUntil(guarded)
  return guarded
}

async function notifyBackend(clientIds: string[]) {
  const url = Deno.env.get('IG_DM_HOOK_URL')?.trim(), key = Deno.env.get('IG_DM_HOOK_KEY')?.trim()
  if (!url || !key) return
  for (const clientId of clientIds) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 90_000) // Render gratuito pode estar acordando
    try {
      const resp = await fetch(url, { method: 'POST', signal: controller.signal,
        headers: { 'content-type': 'application/json', 'x-ig-dm-key': key }, body: JSON.stringify({ client_id: clientId }) })
      console.info({ event: 'ig_dm_backend_notified', status: resp.status })
    } finally {
      clearTimeout(timer)
    }
  }
}

Deno.serve(async (req) => {
  const url = new URL(req.url)
  if (req.method === 'GET') {
    const verify = Deno.env.get('IG_WEBHOOK_VERIFY_TOKEN') || Deno.env.get('WHATSAPP_VERIFY_TOKEN') || ''
    if (url.searchParams.get('hub.mode') === 'subscribe' && verify && url.searchParams.get('hub.verify_token') === verify) {
      return text(url.searchParams.get('hub.challenge') ?? '')
    }
    return text('forbidden', 403)
  }
  if (req.method !== 'POST') return text('method_not_allowed', 405)

  const raw = await req.text()
  const secret = Deno.env.get('META_APP_SECRET') || Deno.env.get('WHATSAPP_APP_SECRET') || ''
  if (!await validSignature(raw, req.headers.get('x-hub-signature-256'), secret)) {
    console.error({ event: 'ig_dm_webhook_bad_signature' })
    return text('unauthorized', 401)
  }
  let payload: Record<string, unknown>
  try { payload = JSON.parse(raw) } catch { return text('invalid_json', 400) }
  const events = dmEvents(payload)
  if (!events.length) return text('ok')

  const supabaseUrl = Deno.env.get('SUPABASE_URL'), serviceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')
  if (!supabaseUrl || !serviceKey) { console.error({ event: 'ig_dm_webhook_server_config' }); return text('ok') }
  const admin = createClient(supabaseUrl, serviceKey)

  const brands = new Map<string, string | null>()
  const pendingClients = new Set<string>()
  let failed = false
  for (const event of events) {
    if (!brands.has(event.igUserId)) {
      const found = await admin.from('meta_connections').select('client_id').eq('platform', 'instagram')
        .eq('ig_user_id', event.igUserId).eq('status', 'active').limit(1)
      if (found.error) { console.error({ event: 'ig_dm_brand_lookup_failed', code: found.error.code }); failed = true; continue }
      brands.set(event.igUserId, found.data?.[0]?.client_id ?? null)
    }
    const clientId = brands.get(event.igUserId)
    if (!clientId) continue
    const saved = await admin.from('ig_dm_messages').upsert({
      client_id: clientId, ig_user_id: event.igUserId, sender_id: event.senderId, mid: event.mid, direction: event.direction,
      text: event.text || null, status: event.direction === 'in' ? 'pendente' : 'registrado', created_at: event.at,
    }, { onConflict: 'mid', ignoreDuplicates: true })
    if (saved.error) { console.error({ event: 'ig_dm_save_failed', code: saved.error.code }); failed = true; continue }
    if (event.direction === 'in') pendingClients.add(clientId)
  }
  if (pendingClients.size) inBackground(notifyBackend([...pendingClients]))
  console.info({ event: 'ig_dm_webhook', messages: events.length, brands: brands.size, failed })
  return failed ? text('retry', 500) : text('ok')
})
