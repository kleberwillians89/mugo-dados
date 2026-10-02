import type {
  MetaAssetBusinessRef,
  MetaDiscoverAssetsResponse,
  MetaDiscoveredAdAccount,
  MetaDiscoveredBusinessManager,
  MetaDiscoveredInstagramAsset,
  MetaDiscoveredPageAsset,
} from "./types";

export type MetaAssetGroup = {
  /** "business:<id>" ou "direct" (ativos sem Business identificado). */
  key: string;
  businessId: string | null;
  businessName: string;
  pages: MetaDiscoveredPageAsset[];
  instagramAccounts: MetaDiscoveredInstagramAsset[];
  adAccounts: MetaDiscoveredAdAccount[];
  /** Consultas do Business recusadas por permissão: o Business pode ter mais ativos. */
  blocked: Array<"ad_accounts" | "pages" | "instagram_accounts">;
  /** Consultas que falharam sem indicar falta de permissão. */
  failed: Array<"ad_accounts" | "pages" | "instagram_accounts">;
  /** Tipos consultados com sucesso para os quais nenhum ativo foi encontrado. */
  empty: Array<"ad_accounts" | "pages" | "instagram_accounts">;
};

export type MetaAssetGrouping = {
  groups: MetaAssetGroup[];
};

/** Identificado pelo Business, mas a autorização atual não permite ler o ativo. */
export function isRestrictedMetaAsset(asset: { access_status?: string }): boolean {
  return asset.access_status === "restricted";
}

function primaryBusiness(refs: MetaAssetBusinessRef[] | undefined): MetaAssetBusinessRef | null {
  const list = refs || [];
  return list.find((ref) => ref.relation === "owned") || list[0] || null;
}

type BusinessAssetKind = "ad_accounts" | "pages" | "instagram_accounts";

function classifyBusinessEdges(
  group: MetaAssetGroup,
  discovery: NonNullable<MetaDiscoveredBusinessManager["discovery"]>,
  kind: BusinessAssetKind,
  owned: "owned_ad_accounts" | "owned_pages" | "owned_instagram_accounts",
  client: "client_ad_accounts" | "client_pages" | "client_instagram_assets",
) {
  const edges = [discovery[owned], discovery[client]].filter(Boolean);
  if (edges.some((edge) => edge?.status === "permission_denied")) {
    group.blocked.push(kind);
    return;
  }
  if (edges.some((edge) => edge?.status === "error" || edge?.status === "rate_limited")) {
    group.failed.push(kind);
    return;
  }
  // Só afirmamos ausência quando os dois edges foram consultados com sucesso.
  if (edges.length === 2 && edges.every((edge) => edge?.status === "ok") && edges.every((edge) => (edge?.count || 0) === 0)) {
    group.empty.push(kind);
  }
}

/**
 * Agrupa os ativos descobertos por Business — só apresentação. Cada ativo
 * aparece uma única vez: no Business dono; senão no Business cliente; sem
 * Business, em "diretamente acessíveis". O Instagram acompanha seu Business
 * quando veio de um edge direto; no fluxo legado, acompanha a Página à qual a
 * Meta o vinculou. Nada aqui seleciona ou grava ativos.
 */
export function groupMetaDiscoveredAssets(
  discovered: Pick<MetaDiscoverAssetsResponse, "pages" | "instagram_accounts" | "ad_accounts" | "business_managers">
): MetaAssetGrouping {
  const businesses = discovered.business_managers || [];
  const businessNames = new Map(businesses.map((business) => [business.business_id, business.business_name || ""]));
  const groups = new Map<string, MetaAssetGroup>();

  function ensure(businessId: string | null, businessName = ""): MetaAssetGroup {
    const key = businessId ? `business:${businessId}` : "direct";
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        businessId,
        businessName: businessId ? businessName || businessNames.get(businessId) || businessId : "",
        pages: [],
        instagramAccounts: [],
        adAccounts: [],
        blocked: [],
        failed: [],
        empty: [],
      };
      groups.set(key, group);
    }
    return group;
  }

  for (const business of businesses) {
    const group = ensure(business.business_id, business.business_name);
    const discovery = business.discovery || {};
    classifyBusinessEdges(group, discovery, "ad_accounts", "owned_ad_accounts", "client_ad_accounts");
    classifyBusinessEdges(group, discovery, "pages", "owned_pages", "client_pages");
    classifyBusinessEdges(group, discovery, "instagram_accounts", "owned_instagram_accounts", "client_instagram_assets");
  }

  const groupOfPage = new Map<string, MetaAssetGroup>();
  for (const page of discovered.pages || []) {
    const ref = primaryBusiness(page.businesses);
    const group = ref ? ensure(ref.business_id, ref.business_name) : ensure(null);
    group.pages.push(page);
    groupOfPage.set(String(page.page_id), group);
  }
  for (const instagram of discovered.instagram_accounts || []) {
    const ref = primaryBusiness(instagram.businesses);
    const pageId = String(instagram.page_id || instagram.business_id || "");
    const group = ref ? ensure(ref.business_id, ref.business_name) : groupOfPage.get(pageId) || ensure(null);
    group.instagramAccounts.push(instagram);
  }
  for (const account of discovered.ad_accounts || []) {
    const ref = primaryBusiness(account.businesses);
    const group = ref ? ensure(ref.business_id, ref.business_name) : ensure(null);
    group.adAccounts.push(account);
  }

  const hasAssets = (group: MetaAssetGroup) =>
    group.pages.length + group.instagramAccounts.length + group.adAccounts.length > 0;
  const all = [...groups.values()];
  const businessGroups = all.filter((group) => group.businessId);
  for (const group of businessGroups) {
    const manager = businesses.find((business) => business.business_id === group.businessId);
    const hasInstagramEdgeStatus = Boolean(
      manager?.discovery?.owned_instagram_accounts || manager?.discovery?.client_instagram_assets
    );
    // Compatibilidade apenas para respostas antigas, anteriores aos edges
    // diretos de Instagram. Respostas novas classificam a ausência pelos dois
    // edges oficiais, sem inferi-la da ausência de Página.
    if (!hasInstagramEdgeStatus && group.empty.includes("pages") && !group.empty.includes("instagram_accounts")) {
      group.empty.push("instagram_accounts");
    } else if (!hasInstagramEdgeStatus &&
      group.pages.length > 0 &&
      group.instagramAccounts.length === 0 &&
      !group.blocked.includes("pages") &&
      !group.failed.includes("pages") &&
      !group.pages.some(isRestrictedMetaAsset)
    ) {
      group.empty.push("instagram_accounts");
    }
  }
  const direct = all.find((group) => group.key === "direct");
  return {
    groups: direct && hasAssets(direct) ? [...businessGroups, direct] : businessGroups,
  };
}
