// Origem de uma conversa: anúncio Click-to-WhatsApp (objeto `referral` da Meta) ou código de entrada
// no texto pré-preenchido de um link/QR ("Oi! (ref:loja-qr)"). Função pura, sem rede nem banco.
// Mesma regra do CRM Mugô (_shared/whatsappOrigin.js), do CRM da Ruah e do backend (services/whatsapp_insights.py).

export type OriginTouch = {
  source: string; referral_source_type: string | null; ad_id: string | null; ctwa_clid: string | null
  source_url: string | null; headline: string | null; body: string | null; media_type: string | null; entry_code: string | null
}

const clean = (value: unknown, max = 240) => String(value ?? '').trim().slice(0, max)
const digitsOnly = (value: unknown) => String(value ?? '').replace(/\D/g, '')

// Só "ref:codigo" (com dois-pontos e começando por letra): "tênis ref 4432" é referência de produto.
const ENTRY_CODE = /(?:^|[\s(\[])ref:\s?([a-z][a-z0-9_-]{1,39})(?=$|[\s)\].,!?])/i

export function extractEntryCode(text: string) {
  const match = ENTRY_CODE.exec(String(text ?? ''))
  return match ? match[1].toLowerCase() : null
}

export function extractOriginTouch(referral: Record<string, unknown> | null | undefined, bodyText = ''): OriginTouch | null {
  const ref = referral && typeof referral === 'object' ? referral : null
  const entryCode = extractEntryCode(bodyText)
  if (!ref && !entryCode) return null
  const type = clean(ref?.source_type, 40)
  const url = clean(ref?.source_url, 1000)
  const isAd = /^ad/i.test(type)
  const adId = digitsOnly(ref?.source_id).slice(0, 30)
  const source = ref ? (isAd ? 'META_ADS_WHATSAPP' : /instagram\./i.test(url) ? 'INSTAGRAM' : 'META_ORGANIC') : 'ENTRY_CODE'
  return {
    source,
    referral_source_type: type || null,
    ad_id: isAd && adId ? adId : null,
    ctwa_clid: clean(ref?.ctwa_clid, 500) || null,
    source_url: url || null,
    headline: clean(ref?.headline) || null,
    body: clean(ref?.body, 500) || null,
    media_type: clean(ref?.media_type, 40) || null,
    entry_code: entryCode,
  }
}

// Chave de telefone para casar conversa e venda SEM o número sair do CRM.
// `international`: o valor já tem código do país (o wa_id sempre tem). Sem isso, 10/11 dígitos sem "+"
// são número nacional (DDD + número, inclusive DDD 55) e ganham o 55. Celular BR com ou sem 9º dígito
// vira a mesma chave (55 + DDD + 8 últimos dígitos).
export function phoneKeySource(value: unknown, { international = false } = {}) {
  const raw = String(value ?? '').trim()
  let d = digitsOnly(raw)
  if (!international && !raw.startsWith('+') && (d.length === 10 || d.length === 11)) d = `55${d}`
  if (d.startsWith('55') && (d.length === 12 || d.length === 13)) return `55${d.slice(2, 4)}${d.slice(-8)}`
  return d.length >= 8 && d.length <= 15 ? d : ''
}

export async function phoneKey(value: unknown, options: { international?: boolean } = {}) {
  const source = phoneKeySource(value, options)
  if (!source) return null
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`mugo-wa:${source}`))
  return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, '0')).join('').slice(0, 32)
}

export function maskPhone(value: unknown) {
  const d = digitsOnly(value)
  return d.length >= 4 ? `•••• ${d.slice(-4)}` : '••••'
}
