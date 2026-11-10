// Peças puras do webhook da Cloud API (testadas em src/app/whatsappWebhook.test.ts).
type Json = Record<string, unknown>
const obj = (value: unknown): Json => (value && typeof value === 'object' ? value as Json : {})

export async function validSignature(raw: string, header: string | null, secret: string) {
  if (!secret || !header?.startsWith('sha256=')) return false
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const mac = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(raw)))
  const expected = [...mac].map((b) => b.toString(16).padStart(2, '0')).join('')
  const given = header.slice(7).toLowerCase()
  if (given.length !== expected.length) return false
  let diff = 0
  for (let i = 0; i < expected.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i)
  return diff === 0
}

const LABELS: Record<string, string> = {
  image: '[imagem]', audio: '[áudio]', video: '[vídeo]', document: '[documento]', sticker: '[figurinha]',
  location: '[localização]', contacts: '[contato]',
}

export function messageText(message: Json) {
  const type = String(message.type ?? '')
  if (type === 'text') return String(obj(message.text).body ?? '')
  if (type === 'button') return String(obj(message.button).text ?? '')
  if (type === 'interactive') {
    const interactive = obj(message.interactive)
    return String(obj(interactive.button_reply).title ?? obj(interactive.list_reply).title ?? '')
  }
  if (type === 'reaction') return ''
  const caption = String(obj(message[type]).caption ?? '').trim()
  return `${LABELS[type] ?? `[${type || 'mensagem'}]`}${caption ? ` ${caption}` : ''}`
}

