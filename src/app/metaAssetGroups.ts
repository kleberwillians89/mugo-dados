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
  blocked: Array<"ad_accounts" | "pages">;
};

export type MetaAssetGrouping = {
  groups: MetaAssetGroup[];
  /** Businesses consultados sem nenhum ativo para esta autorização. */
  emptyBusinesses: MetaDiscoveredBusinessManager[];
};

/** Identificado pelo Business, mas a autorização atual não permite ler o ativo. */
export function isRestrictedMetaAsset(asset: { access_status?: string }): boolean {
  return asset.access_status === "restricted";
}

function primaryBusiness(refs: MetaAssetBusinessRef[] | undefined): MetaAssetBusinessRef | null {
  const list = refs || [];
  return list.find((ref) => ref.relation === "owned") || list[0] || null;
}

/**
 * Agrupa os ativos descobertos por Business — só apresentação. Cada ativo
 * aparece uma única vez: no Business dono; senão no Business cliente; sem
 * Business, em "diretamente acessíveis". O Instagram acompanha a Página à qual
 * a Meta o vinculou (business_id do Instagram = ID da Página). Nada aqui
 * seleciona ou grava ativos.
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
      };
      groups.set(key, group);
    }
    return group;
  }

  for (const business of businesses) {
    const group = ensure(business.business_id, business.business_name);
    const discovery = business.discovery || {};
    if (discovery.owned_ad_accounts?.status === "permission_denied" || discovery.client_ad_accounts?.status === "permission_denied") {
      group.blocked.push("ad_accounts");
    }
    if (discovery.owned_pages?.status === "permission_denied" || discovery.client_pages?.status === "permission_denied") {
      group.blocked.push("pages");
    }
  }

  const groupOfPage = new Map<string, MetaAssetGroup>();
  for (const page of discovered.pages || []) {
    const ref = primaryBusiness(page.businesses);
    const group = ref ? ensure(ref.business_id, ref.business_name) : ensure(null);
    group.pages.push(page);
    groupOfPage.set(String(page.page_id), group);
  }
  for (const instagram of discovered.instagram_accounts || []) {
    const group = groupOfPage.get(String(instagram.business_id || "")) || ensure(null);
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
  const businessGroups = all.filter((group) => group.businessId && (hasAssets(group) || group.blocked.length > 0));
  const direct = all.find((group) => group.key === "direct");
  return {
    groups: direct && hasAssets(direct) ? [...businessGroups, direct] : businessGroups,
    emptyBusinesses: businesses.filter((business) => {
      const group = groups.get(`business:${business.business_id}`);
      return Boolean(group) && !hasAssets(group!) && group!.blocked.length === 0;
    }),
  };
}
