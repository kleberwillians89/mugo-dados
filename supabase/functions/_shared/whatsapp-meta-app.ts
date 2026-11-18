// Seleciona credenciais de webhook Meta por aplicativo, sem fallback entre apps.
// Sem ?meta_app_id= preserva a integracao legada da Mugo no Mugo Dados.
const safe = (value: string | undefined | null) => String(value ?? '').trim()
export type MetaWebhookApp = { appId: string | null; verifyToken: string; appSecret: string; legacy: boolean }
export function resolveMetaWebhookApp(url: URL, env: (key: string) => string | undefined | null): MetaWebhookApp | null {
  if (!url.searchParams.has('meta_app_id')) {
    return { appId: null, verifyToken: safe(env('WHATSAPP_VERIFY_TOKEN')), appSecret: safe(env('WHATSAPP_APP_SECRET')), legacy: true }
  }
  const appId = url.searchParams.get('meta_app_id') || ''
  if (!/^[0-9]{5,30}$/.test(appId)) return null
  const verifyToken = safe(env(`META_APP_${appId}_WEBHOOK_VERIFY_TOKEN`))
  if (!verifyToken) return null
  return { appId, verifyToken, appSecret: safe(env(`META_APP_${appId}_APP_SECRET`)), legacy: false }
}
export function webhookMatchesNumber(app: MetaWebhookApp, number: { meta_app_id?: string | null; waba_id?: string | null }, entryWabaId: string): boolean {
  const actualAppId = String(number.meta_app_id || '')
  if (app.legacy ? actualAppId !== '' : actualAppId !== app.appId) return false
  return Boolean(entryWabaId && number.waba_id && entryWabaId === String(number.waba_id))
}
