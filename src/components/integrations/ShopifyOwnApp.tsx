import { useEffect, useState } from "react";
import { readShopifyOwnApps, saveShopifyOwnApp, type ShopifyOwnApps } from "../../app/onboardingApi";

/**
 * App Shopify desta loja. A Shopify só instala app de distribuição personalizada na loja para a qual ele foi gerado,
 * então cada cliente tem o próprio app no Dev Dashboard. Aqui a equipe Mugô cola o Client ID e o Client Secret dele;
 * o segredo é guardado criptografado e nunca volta para a tela. Sem cadastro, a conexão usa o app padrão.
 */
export default function ShopifyOwnApp({ shopDomain }: { shopDomain: string }) {
  const [data, setData] = useState<ShopifyOwnApps | null>(null);
  const [shop, setShop] = useState(shopDomain);
  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => { readShopifyOwnApps().then(setData).catch(() => setData({ apps: [] })); }, []);

  async function save() {
    setBusy(true); setNote(null);
    try {
      const out = await saveShopifyOwnApp({ shop_domain: shop.trim(), app_client_id: appId.trim(), client_secret: secret.trim() });
      setData(out); setSecret(""); setAppId("");
      setNote({ ok: true, text: "App salvo. Agora clique em conectar: a Shopify vai abrir a instalação deste app na loja." });
    } catch (cause) {
      setNote({ ok: false, text: cause instanceof Error && cause.message ? cause.message : "Não foi possível salvar o app." });
    } finally { setBusy(false); }
  }

  const apps = data?.apps || [];
  return <details className="shopifyOwnApp" style={{ marginTop: 12 }}>
    <summary>App Shopify desta loja {apps.length ? `· ${apps.map((a) => `${a.shop_domain} (${a.client_id_hint})`).join(", ")}` : "· usando o app padrão"}</summary>
    <p style={{ fontSize: 13, color: "var(--text-muted, #687178)", margin: "8px 0" }}>
      Cada loja instala só o app criado para ela (Dev Dashboard → distribuição personalizada). Cole aqui o Client ID e o
      Client Secret do app desta loja. O segredo fica criptografado e não aparece de novo.
    </p>
    <div style={{ display: "grid", gap: 8 }}>
      <input aria-label="Domínio da loja" placeholder="loja.myshopify.com" value={shop} onChange={(e) => setShop(e.target.value)} disabled={busy} />
      <input aria-label="Client ID" placeholder="Client ID" value={appId} onChange={(e) => setAppId(e.target.value)} disabled={busy} autoComplete="off" />
      <input aria-label="Client Secret" placeholder="Client Secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} disabled={busy} autoComplete="new-password" />
      <button type="button" className="btn btnGhost" disabled={busy || !shop.trim() || !appId.trim() || !secret.trim()} onClick={() => void save()}>
        {busy ? "Salvando…" : apps.some((a) => a.shop_domain === shop.trim()) ? "Trocar o app desta loja" : "Salvar app da loja"}</button>
      {note ? <p role={note.ok ? "status" : "alert"} style={{ margin: 0, fontSize: 13, color: note.ok ? "#1f6b45" : "#b42318" }}>{note.text}</p> : null}
    </div>
  </details>;
}
