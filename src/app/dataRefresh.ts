/**
 * "Atualizar dados" seguro: revalidação do que já está persistido.
 *
 * NÃO é sincronização de provider. O botão administrativo chama Meta, Google,
 * FBITS e Shopify; a FBITS bloqueia o token da loja por uma hora depois de
 * insistir no 429, então deixar qualquer membro disparar isso derrubaria a
 * integração da empresa inteira. Aqui a ação relê os endpoints de leitura que
 * o usuário já tem direito de ler — nenhum privilégio novo, nenhuma chamada a
 * terceiro, nenhum custo de IA.
 *
 * O cooldown existe para que um clique repetido não vire enxurrada de
 * requisições; a deduplicação de chamadas concorrentes continua em
 * `syncOrchestrator`.
 */

export const REFRESH_COOLDOWN_MS = 30_000;

/** Texto de frescor em português, relativo e sem precisão falsa. */
export function formatFreshness(iso: string | null | undefined, now: number = Date.now()): string | null {
  const value = String(iso || "").trim();
  if (!value) return null;
  const at = new Date(value).getTime();
  if (Number.isNaN(at)) return null;
  const minutes = Math.floor(Math.max(0, now - at) / 60_000);
  if (minutes < 1) return "agora mesmo";
  if (minutes === 1) return "há 1 min";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours === 1) return "há 1 h";
  if (hours < 24) return `há ${hours} h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "há 1 dia" : `há ${days} dias`;
}

export type RefreshCooldown = {
  /** Pode disparar agora? */
  ready: boolean;
  /** Segundos que faltam, 0 quando liberado. */
  secondsLeft: number;
};

export function cooldownFrom(
  lastAttemptAt: number | null,
  now: number = Date.now(),
  windowMs: number = REFRESH_COOLDOWN_MS,
): RefreshCooldown {
  if (!lastAttemptAt) return { ready: true, secondsLeft: 0 };
  const remaining = lastAttemptAt + windowMs - now;
  if (remaining <= 0) return { ready: true, secondsLeft: 0 };
  return { ready: false, secondsLeft: Math.ceil(remaining / 1000) };
}

/** Rótulo discreto do cooldown, sem alarmar. */
export function cooldownHint(cooldown: RefreshCooldown): string | null {
  if (cooldown.ready) return null;
  return `Aguarde ${cooldown.secondsLeft}s para atualizar de novo.`;
}

/**
 * Os dados das integrações ficaram mais novos que a análise entregue?
 *
 * Serve para avisar, não para gerar nada: a permissão de gerar análise
 * continua exatamente onde está.
 */
export function hasFresherData(
  dataUpdatedAt: string | null | undefined,
  analysisGeneratedAt: string | null | undefined,
): boolean {
  const data = new Date(String(dataUpdatedAt || "")).getTime();
  const analysis = new Date(String(analysisGeneratedAt || "")).getTime();
  if (Number.isNaN(data) || Number.isNaN(analysis)) return false;
  // Um minuto de folga: relógios de job e de banco não batem ao segundo.
  return data - analysis > 60_000;
}
