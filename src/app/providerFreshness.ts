/**
 * "Esta empresa já teve dado deste provider?" — decidido pelo DADO, nunca pela
 * telemetria de sincronização.
 *
 * O Google Ads provou o problema: a sincronização não registrava
 * `last_success_at`, então a tela anunciava "aguardando a primeira importação"
 * para quem já tinha números. `data_max_available` vem do read model e só
 * existe quando há linha gravada, então não depende de o sync ter deixado
 * rastro.
 *
 * Com dado já existente, um refresh que falha nunca pode virar estado vazio,
 * zero temporário ou mensagem de primeira importação: a tela mantém a última
 * leitura válida e, no máximo, diz discretamente quando foi atualizada.
 */

export type ProviderSourceSnapshot = {
  provider?: string | null;
  last_success_at?: string | null;
  data_max_available?: string | null;
  /** Só diagnóstico: nunca entra no "atualizado em" mostrado ao cliente. */
  last_attempt_at?: string | null;
};

function text(value: unknown): string {
  return String(value ?? "").trim();
}

export function findProviderSource(
  sources: ProviderSourceSnapshot[] | null | undefined,
  provider: string
): ProviderSourceSnapshot | null {
  const wanted = text(provider).toLowerCase();
  if (!wanted) return null;
  return (sources || []).find((item) => text(item?.provider).toLowerCase() === wanted) || null;
}

export function providerEverHadData(
  sources: ProviderSourceSnapshot[] | null | undefined,
  provider: string,
  fallbacks: { lastSuccessAt?: string | null; hasDataNow?: boolean } = {}
): boolean {
  if (fallbacks.hasDataNow) return true;
  if (text(fallbacks.lastSuccessAt)) return true;
  const source = findProviderSource(sources, provider);
  return Boolean(text(source?.data_max_available) || text(source?.last_success_at));
}

export type SyncNotice = { title: string; body: string };

/**
 * Aviso do bloco de mídia paga, em linguagem de cliente.
 *
 * Sem jargão de pipeline ("job", "sync", "importação") e sem erro técnico cru:
 * o diagnóstico fica no log e na tela de Integrações. Um resultado parcial
 * continua não passando por sucesso — só é dito sem vocabulário interno.
 */
export function paidMediaNotice(input: {
  provider: string;
  syncStatus?: string | null;
  everHadData: boolean;
}): SyncNotice {
  const status = text(input.syncStatus).toLowerCase();
  const label = text(input.provider) || "Mídia paga";
  if (status === "partial") {
    return {
      title: `Dados de ${label} incompletos neste período`,
      body: `A ${label} não retornou todos os números do período. Os valores podem mudar na próxima atualização.`,
    };
  }
  if (status === "skipped" || input.everHadData) {
    return {
      title: `Ainda não há dados de ${label} para este período`,
      body: "A conta está conectada, mas não há investimento registrado no período selecionado.",
    };
  }
  return {
    title: `Ainda não há dados de ${label}`,
    body: "A conta está conectada e os números aparecem aqui quando houver investimento registrado.",
  };
}


/**
 * Timestamp do "atualizado em" para o cliente: SEMPRE leitura válida.
 *
 * `last_attempt_at` é ignorado de propósito. Um provider consultado sem dado
 * novo, ou com erro, não pode parecer recém-atualizado — senão a tela promete
 * frescor que não existe. Erro também não altera o valor: fica o último
 * sucesso.
 */
export function providerValidUpdatedAt(
  sources: ProviderSourceSnapshot[] | null | undefined,
  provider: string,
  fallbacks: { lastSuccessAt?: string | null } = {}
): string | null {
  const source = findProviderSource(sources, provider);
  return text(source?.last_success_at) || text(fallbacks.lastSuccessAt) || null;
}
