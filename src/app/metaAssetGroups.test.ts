import { describe, expect, it } from "vitest";
import { groupMetaDiscoveredAssets, isRestrictedMetaAsset } from "./metaAssetGroups";

// IDs do caso RÜAH e da Mugô: só fixtures de apresentação.
const RUAH = { business_id: "2633867063339117", business_name: "RÜAH" };
const MUGO = { business_id: "585767010886087", business_name: "Mugô" };

describe("groupMetaDiscoveredAssets — seletor Meta agrupado por Business", () => {
  it("agrupa Página, Instagram (pelo vínculo da Página) e contas pelo Business dono; diretos ao final", () => {
    const { groups } = groupMetaDiscoveredAssets({
      business_managers: [RUAH, MUGO],
      pages: [
        { page_id: "516985944838234", page_name: "Mugô", businesses: [{ ...MUGO, relation: "owned" }] },
        { page_id: "page-solta", page_name: "Página pessoal" },
      ],
      instagram_accounts: [
        { ig_user_id: "17841471880135733", username: "mugo", business_id: "516985944838234" },
        { ig_user_id: "ig-solto", username: "solto", business_id: "page-solta" },
      ],
      ad_accounts: [
        { ad_account_id: "act_1391863696277834", businesses: [{ ...RUAH, relation: "owned" }] },
        { ad_account_id: "act_8024076734300108", businesses: [{ ...MUGO, relation: "owned" }] },
        { ad_account_id: "act_direta" },
      ],
    });
    expect(groups.map((group) => group.key)).toEqual([
      "business:2633867063339117", "business:585767010886087", "direct",
    ]);
    const [ruah, mugo, direct] = groups;
    expect(ruah.businessName).toBe("RÜAH");
    expect(ruah.adAccounts.map((account) => account.ad_account_id)).toEqual(["act_1391863696277834"]);
    expect(mugo.pages.map((page) => page.page_id)).toEqual(["516985944838234"]);
    expect(mugo.instagramAccounts.map((ig) => ig.ig_user_id)).toEqual(["17841471880135733"]);
    expect(direct.instagramAccounts.map((ig) => ig.ig_user_id)).toEqual(["ig-solto"]);
    expect(direct.adAccounts.map((account) => account.ad_account_id)).toEqual(["act_direta"]);
  });

  it("conta vista como dona e como cliente aparece uma única vez, no Business dono", () => {
    const { groups } = groupMetaDiscoveredAssets({
      business_managers: [{ business_id: "agencia", business_name: "Agência" }, RUAH],
      pages: [],
      instagram_accounts: [],
      ad_accounts: [{
        ad_account_id: "act_1",
        businesses: [
          { business_id: "agencia", business_name: "Agência", relation: "client" },
          { ...RUAH, relation: "owned" },
        ],
      }],
    });
    const all = groups.flatMap((group) => group.adAccounts.map((account) => `${group.key}:${account.ad_account_id}`));
    expect(all).toEqual([`business:${RUAH.business_id}:act_1`]);
  });

  it("distingue Business sem ativos, permissão negada e falha de consulta", () => {
    const { groups } = groupMetaDiscoveredAssets({
      business_managers: [
        { business_id: "bloqueado", business_name: "Bloqueado", discovery: { owned_ad_accounts: { status: "permission_denied" }, client_ad_accounts: { status: "ok", count: 0 } } },
        { business_id: "vazio", business_name: "Vazio", discovery: {
          owned_ad_accounts: { status: "ok", count: 0 }, client_ad_accounts: { status: "ok", count: 0 },
          owned_pages: { status: "ok", count: 0 }, client_pages: { status: "ok", count: 0 },
        } },
        { business_id: "falhou", business_name: "Falhou", discovery: { owned_ad_accounts: { status: "error" }, client_ad_accounts: { status: "ok", count: 0 } } },
      ],
      pages: [],
      instagram_accounts: [],
      ad_accounts: [],
    });
    expect(groups.map((group) => group.key)).toEqual(["business:bloqueado", "business:vazio", "business:falhou"]);
    expect(groups[0].blocked).toEqual(["ad_accounts"]);
    expect(groups[0].empty).not.toContain("ad_accounts");
    expect(groups[1].empty).toEqual(["ad_accounts", "pages", "instagram_accounts"]);
    expect(groups[1].blocked).toEqual([]);
    expect(groups[1].failed).toEqual([]);
    expect(groups[2].failed).toEqual(["ad_accounts"]);
    expect(groups[2].empty).not.toContain("ad_accounts");
  });

  it("Business com Página/Instagram e sem Ads mantém os ativos e marca apenas Ads como vazio", () => {
    const business = {
      business_id: "origami", business_name: "origami_investimentos", discovery: {
        owned_ad_accounts: { status: "ok" as const, count: 0 }, client_ad_accounts: { status: "ok" as const, count: 0 },
        owned_pages: { status: "ok" as const, count: 1 }, client_pages: { status: "ok" as const, count: 0 },
      },
    };
    const { groups } = groupMetaDiscoveredAssets({
      business_managers: [business],
      pages: [{ page_id: "page-origami", businesses: [{ business_id: "origami", business_name: "origami_investimentos", relation: "owned" }] }],
      instagram_accounts: [{ ig_user_id: "ig-origami", business_id: "page-origami" }],
      ad_accounts: [],
    });
    expect(groups).toHaveLength(1);
    expect(groups[0].pages).toHaveLength(1);
    expect(groups[0].instagramAccounts).toHaveLength(1);
    expect(groups[0].empty).toEqual(["ad_accounts"]);
  });

  it("sem Business, mantém tudo em um único grupo direto (comportamento anterior)", () => {
    const { groups } = groupMetaDiscoveredAssets({
      business_managers: [],
      pages: [{ page_id: "p1" }],
      instagram_accounts: [{ ig_user_id: "ig1", business_id: "p1" }],
      ad_accounts: [{ ad_account_id: "act_1" }],
    });
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe("direct");
  });

  it("identifica ativo restrito pelo estado de acesso devolvido pelo backend", () => {
    expect(isRestrictedMetaAsset({ access_status: "restricted" })).toBe(true);
    expect(isRestrictedMetaAsset({ access_status: "accessible" })).toBe(false);
    expect(isRestrictedMetaAsset({ access_status: "unverified" })).toBe(false);
    expect(isRestrictedMetaAsset({})).toBe(false);
  });
});
