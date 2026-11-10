// Webhook do WhatsApp (Cloud API da Meta) do app da Mugô, para TODOS os números ligados ao MUGOVERSO.
//
// GET: verificação do webhook (hub.challenge com WHATSAPP_VERIFY_TOKEN).
// POST: confere a assinatura (X-Hub-Signature-256 com WHATSAPP_APP_SECRET), descobre a empresa pelo
// phone_number_id e grava conversa, mensagem, origem (anúncio / ref:codigo) e status de entrega.
//
// Número que NÃO está em whatsapp_numbers (hoje: o da Mugô, que vive no CRM Mugô) → o corpo original é
// repassado sem alteração, com a mesma assinatura, para WHATSAPP_FORWARD_URL. O CRM confere a assinatura
// com o mesmo segredo do app e ignora números que não são dele.
//
// Responde 500 quando o banco falha, para a Meta reenviar (a gravação é idempotente: mensagem repetida
// não duplica nem conta "não lida" em dobro). Número desligado no MUGOVERSO: a mensagem é descartada e
// NÃO vai para o CRM.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { extractOriginTouch, phoneKey } from '../_shared/whatsapp-origin.ts'
import { messageText, validSignature } from '../_shared/whatsapp-cloud.ts'

const text = (body: string, status = 200) => new Response(body, { status, headers: { 'content-type': 'text/plain' } })
const digits = (value: unknown) => String(value ?? '').replace(/\D/g, '')
type Json = Record<string, unknown>
const obj = (value: unknown): Json => (value && typeof value === 'object' ? value as Json : {})
const list = (value: unknown): Json[] => (Array.isArray(value) ? value.map(obj) : [])

const STATUS_RANK: Record<string, number> = { sent: 1, delivered: 2, read: 3, failed: 4 }

function inBackground(task: Promise<unknown>) {
  const guarded = task.catch((error) => console.error({ event: 'whatsapp_background_failed', message: String(error).slice(0, 200) }))
  const runtime = (globalThis as unknown as { EdgeRuntime?: { waitUntil(p: Promise<unknown>): void } }).EdgeRuntime
  if (runtime?.waitUntil) runtime.waitUntil(guarded)
  return guarded
}

async function forward(raw: string, signature: string) {
  const url = Deno.env.get('WHATSAPP_FORWARD_URL')?.trim()
  if (!url) return
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 15_000)
  try {
    const resp = await fetch(url, { method: 'POST', body: raw, signal: controller.signal,
      headers: { 'content-type': 'application/json', 'x-hub-signature-256': signature } })
    console.info({ event: 'whatsapp_forwarded', status: resp.status })
  } finally {
    clearTimeout(timer)
  }
}

Deno.serve(async (req) => {
  const url = new URL(req.url)
  if (req.method === 'GET') {
    const verify = Deno.env.get('WHATSAPP_VERIFY_TOKEN') ?? ''
    if (url.searchParams.get('hub.mode') === 'subscribe' && verify && url.searchParams.get('hub.verify_token') === verify) {
      return text(url.searchParams.get('hub.challenge') ?? '')
    }
    return text('forbidden', 403)
  }
  if (req.method !== 'POST') return text('method_not_allowed', 405)

  const raw = await req.text()
  const signature = req.headers.get('x-hub-signature-256')
  if (!await validSignature(raw, signature, Deno.env.get('WHATSAPP_APP_SECRET') ?? '')) {
    console.error({ event: 'whatsapp_webhook_bad_signature' })
    return text('unauthorized', 401)
  }
  let payload: Json
  try { payload = obj(JSON.parse(raw)) } catch { return text('invalid_json', 400) }

  const supabaseUrl = Deno.env.get('SUPABASE_URL'), serviceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')
  if (!supabaseUrl || !serviceKey) { console.error({ event: 'whatsapp_webhook_server_config' }); return text('ok') }
  const admin = createClient(supabaseUrl, serviceKey)

  const numbers = new Map<string, { id: string; client_id: string; status: string } | null>()
  let foreign = false, failed = false, saved = 0
  for (const entry of list(payload.entry)) {
    for (const change of list(entry.changes)) {
      const value = obj(change.value)
      const phoneNumberId = digits(obj(value.metadata).phone_number_id)
      if (!phoneNumberId) continue
      if (!numbers.has(phoneNumberId)) {
        const found = await admin.from('whatsapp_numbers').select('id,client_id,status').eq('phone_number_id', phoneNumberId).maybeSingle()
        if (found.error) { console.error({ event: 'whatsapp_number_lookup_failed', code: found.error.code }); failed = true; continue }
        numbers.set(phoneNumberId, found.data)
      }
      const number = numbers.get(phoneNumberId)
      if (number === undefined) continue
      if (!number) { foreign = true; continue }
      if (number.status !== 'active') continue

      const contacts = list(value.contacts)
      for (const message of list(value.messages)) {
        const waId = digits(message.from)
        const providerMessageId = String(message.id ?? '').slice(0, 200)
        const body = messageText(message).trim()
        if (!waId || !providerMessageId || !body) continue
        const key = await phoneKey(waId, { international: true })
        if (!key) continue
        const contact = contacts.find((row) => digits(row.wa_id) === waId) ?? contacts[0]
        const sentAt = new Date((Number(message.timestamp) || Date.now() / 1000) * 1000).toISOString()
        const result = await admin.rpc('whatsapp_receive_v1', {
          p_number_id: number.id, p_wa_id: waId, p_phone_key: key, p_profile_name: String(obj(contact?.profile).name ?? ''),
          p_provider_message_id: providerMessageId, p_type: String(message.type ?? 'text'), p_text: body.slice(0, 4096), p_sent_at: sentAt,
        })
        if (result.error) { console.error({ event: 'whatsapp_receive_failed', code: result.error.code }); failed = true; continue }
        const data = obj(result.data)
        if (data.status !== 'ok') continue
        saved += 1
        const touch = extractOriginTouch(message.referral ? obj(message.referral) : null, body)
        if (touch) {
          const stored = await admin.from('whatsapp_origin_touches').upsert(
            { client_id: number.client_id, thread_id: data.thread_id, provider_message_id: providerMessageId, ...touch, occurred_at: sentAt },
            { onConflict: 'thread_id,provider_message_id', ignoreDuplicates: true })
          if (stored.error) console.error({ event: 'whatsapp_origin_touch_failed', code: stored.error.code })
        }
      }

      for (const status of list(value.statuses)) {
        const next = String(status.status ?? '')
        const providerMessageId = String(status.id ?? '')
        if (!STATUS_RANK[next] || !providerMessageId) continue
        // Só avança (sent → delivered → read; failed vence tudo), numa atualização condicional só.
        const lower = Object.keys(STATUS_RANK).filter((key) => STATUS_RANK[key] < STATUS_RANK[next]).concat('received')
        const at = new Date((Number(status.timestamp) || Date.now() / 1000) * 1000).toISOString()
        const errorCode = list(status.errors)[0]?.code
        const updated = await admin.from('whatsapp_messages').update({
          status: next, ...(next === 'read' ? { read_at: at } : {}), ...(errorCode ? { error_code: String(errorCode).slice(0, 40) } : {}),
        }).eq('number_id', number.id).eq('provider_message_id', providerMessageId).eq('direction', 'out').in('status', lower)
        if (updated.error) { console.error({ event: 'whatsapp_status_failed', code: updated.error.code }); failed = true }
      }
    }
  }

  if (foreign && signature) inBackground(forward(raw, signature))
  console.info({ event: 'whatsapp_webhook_processed', saved, forwarded: foreign, failed })
  return failed ? text('retry', 500) : text('ok')
})
