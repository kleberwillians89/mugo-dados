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
 * Aviso do bloco de mídia paga. "Aguardando sincronização válida" só quando a
 * empresa nunca teve dado — com dado, a leitura é "não houve investimento
 * neste período", que é o fato.
 */
export function paidMediaNotice(input: {
  provider: string;
  syncStatus?: string | null;
  everHadData: boolean;
  lastError?: string | null;
}): SyncNotice {
  const status = text(input.syncStatus).toLowerCase();
  const label = text(input.provider) || "Mídia paga";
  if (status === "skipped" || status === "partial") {
    return {
      title: status === "skipped" ? `${label} sem dados no período` : `Importação de ${label} parcial`,
      body: text(input.lastError) || "A plataforma não retornou dados agregados para o período.",
    };
  }
  if (input.everHadData) {
    return {
      title: `Sem dados de ${label} neste período`,
      body: "A conta está conectada, mas não há investimento registrado no período selecionado.",
    };
  }
  return {
    title: "Aguardando sincronização válida",
    body: `${label} conectado. Os números aparecem assim que a primeira importação terminar.`,
  };
}
