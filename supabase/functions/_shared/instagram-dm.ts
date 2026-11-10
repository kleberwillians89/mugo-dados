// Peças puras do webhook do Direct do Instagram (testadas em src/app/instagramWebhook.test.ts).
type Json = Record<string, unknown>
const obj = (value: unknown): Json => (value && typeof value === 'object' ? value as Json : {})
const list = (value: unknown): Json[] => (Array.isArray(value) ? value.map(obj) : [])

export type DmEvent = {
  igUserId: string // conta da marca
  senderId: string // IGSID da pessoa (do outro lado da conversa)
  mid: string
  direction: 'in' | 'out'
  text: string
  at: string
}

const ATTACHMENT_LABELS: Record<string, string> = {
  image: '[imagem]', video: '[vídeo]', audio: '[áudio]', file: '[arquivo]', share: '[post compartilhado]',
  story_mention: '[menção no story]', reel: '[reels]', ig_reel: '[reels]', animated_image: '[gif]',
}

function messageText(message: Json): string {
  const text = String(message.text ?? '').trim()
  if (text) return text.slice(0, 2000)
  const kinds = list(message.attachments).map((a) => ATTACHMENT_LABELS[String(a.type ?? '')] ?? '[anexo]')
  return kinds.join(' ').slice(0, 2000)
}

/** Mensagens (recebidas e ecos do que a marca mandou). Leitura, reação, apagada e não suportada ficam de fora. */
export function dmEvents(payload: Json): DmEvent[] {
  if (payload.object !== 'instagram') return []
  const out: DmEvent[] = []
  for (const entry of list(payload.entry)) {
    const igUserId = String(entry.id ?? '').trim()
    for (const item of list(entry.messaging)) {
      const message = obj(item.message)
      const mid = String(message.mid ?? '').trim()
      if (!igUserId || !mid || message.is_deleted || message.is_unsupported) continue
      const echo = Boolean(message.is_echo)
      const senderId = String(obj(echo ? item.recipient : item.sender).id ?? '').trim()
      if (!senderId || senderId === igUserId) continue
      const ts = Number(item.timestamp)
      out.push({ igUserId, senderId, mid: mid.slice(0, 300), direction: echo ? 'out' : 'in', text: messageText(message),
        at: Number.isFinite(ts) && ts > 0 ? new Date(ts).toISOString() : new Date().toISOString() })
    }
  }
  return out
}
