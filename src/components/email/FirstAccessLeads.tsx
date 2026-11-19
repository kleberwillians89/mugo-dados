import { useCallback, useEffect, useMemo, useState } from "react";
import { http } from "../../app/api";
import { getActiveClientId } from "../../app/activeClient";
import GroupInviteCampaigns from "./GroupInviteCampaigns";

type Summary = {
  total: number; unique: number; email_opt_in_claimed: number;
  whatsapp_opt_in_claimed: number; consent_verified: number; pending_validation: number;
  daily: {day: string; leads: number}[];
  sources: {source: string; leads: number}[];
};
type Recent = {
  id: string; name: string; email_masked: string; phone_masked: string;
  utm_source: string; consent_verified: boolean;
};
type CaptureSource = {
  id: string; name: string; kind: string; active: boolean; last_received_at?: string | null;
};
type CaptureCampaign = {key: string; leads: number; last_received_at: string | null};

const SLUG = /^[a-z0-9][a-z0-9_-]{1,79}$/;
function normalizeSlug(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80);
}
function makeLink(base: string, campaign: string, source: string): string | null {
  try {
    const url = new URL(base);
    if (!["https:", "http:"].includes(url.protocol) || !SLUG.test(campaign)) return null;
    url.searchParams.set("mugo_campaign", campaign);
    url.searchParams.set("utm_source", source);
    url.searchParams.set("utm_medium", "paid_social");
    url.searchParams.set("utm_campaign", campaign);
    return url.toString();
  } catch { return null; }
}
function Stat({label,value}:{label:string;value:string|number}) {
  return <div className="emCaptureStat">
    <strong>{value}</strong><span>{label}</span>
  </div>;
}

/** Relationship Capture: tenant-aware sources + campaign links, no sending permissions. */
export default function FirstAccessLeads({canEdit = false}:{canEdit?: boolean}) {
  const clientId = getActiveClientId();
  const isRoove = clientId === "roove";
  const [campaign, setCampaign] = useState(isRoove ? "roove_first_access_2026" : "");
  const [landing, setLanding] = useState(isRoove ?
    "https://www.roove.com.br/pages/your-first-skinwear-roove-first-access" : "");
  const [campaigns, setCampaigns] = useState<CaptureCampaign[]>([]);
  const [sources, setSources] = useState<CaptureSource[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [sourceName, setSourceName] = useState("");
  const [sourceKind, setSourceKind] = useState("custom_form");
  const [issuedKey, setIssuedKey] = useState<{id:string;key:string}|null>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);

  const safeCampaign = SLUG.test(campaign) ? campaign : "";
  const links = useMemo(() => ({
    instagram: makeLink(landing, safeCampaign, "instagram"),
    facebook: makeLink(landing, safeCampaign, "facebook"),
  }), [landing, safeCampaign]);
  const metaParams = `utm_source={{site_source_name}}&utm_medium=paid_social&utm_campaign=${safeCampaign}&utm_content={{ad.id}}&utm_term={{adset.id}}&meta_campaign_id={{campaign.id}}&meta_placement={{placement}}&mugo_campaign=${safeCampaign}`;

  const refresh = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError("");
    try {
      const [campaignResult, sourceResult] = await Promise.all([
        http<{campaigns: CaptureCampaign[]}>(`/api/relationship/capture-campaigns?client_id=${encodeURIComponent(clientId)}`),
        http<{sources: CaptureSource[]}>(`/api/relationship/lead-sources?client_id=${encodeURIComponent(clientId)}`),
      ]);
      if (getActiveClientId() !== clientId) return;
      setCampaigns(campaignResult.campaigns || []);
      setSources(sourceResult.sources || []);
      if (safeCampaign) {
        const report = await http<Summary>(`/api/relationship/campaigns/${encodeURIComponent(safeCampaign)}/summary?client_id=${encodeURIComponent(clientId)}`);
        if (getActiveClientId() !== clientId) return;
        setSummary(report);
        if (canEdit) {
          const response = await http<{contacts:Recent[]}>(`/api/relationship/campaigns/${encodeURIComponent(safeCampaign)}/recent?client_id=${encodeURIComponent(clientId)}`);
          if (getActiveClientId() === clientId) setRecent(response.contacts || []);
        }
      } else { setSummary(null); setRecent([]); }
    } catch (err) {
      if (getActiveClientId() === clientId) setError(err instanceof Error ? err.message : "Não foi possível carregar a captação.");
    } finally { if (getActiveClientId() === clientId) setLoading(false); }
  }, [clientId, safeCampaign, canEdit]);

  useEffect(() => {
    setSummary(null); setRecent([]); setIssuedKey(null);
    void refresh();
  }, [refresh]);

  async function createSource() {
    if (!clientId || !sourceName.trim() || !canEdit) return;
    setCreating(true); setError(""); setIssuedKey(null);
    try {
      const result = await http<{source:CaptureSource & {ingest_key:string}}>(
        `/api/relationship/lead-sources?client_id=${encodeURIComponent(clientId)}`,
        {method:"POST",headers:{"Content-Type":"application/json"},
         body:JSON.stringify({name:sourceName.trim(),kind:sourceKind})}
      );
      if (getActiveClientId() !== clientId) return;
      setIssuedKey({id:result.source.id,key:result.source.ingest_key});
      setSourceName("");
      setSources(previous => [result.source, ...previous]);
      setInfo("Fonte criada. A chave é exibida uma única vez; guarde-a em um gerenciador seguro.");
    } catch (err) { setError(err instanceof Error ? err.message : "Falha ao criar fonte."); }
    finally {setCreating(false);}
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setInfo("Copiado para a área de transferência."); }
    catch { setError("Não foi possível copiar automaticamente."); }
  }

  return <section className="emFirstAccess emCapture" aria-label="Captação e campanhas">
    <header className="emCaptureHero">
      <div><span className="emCaptureEyebrow">RELACIONAMENTO / CAPTAÇÃO</span>
      <h2>Campanhas que viram conexões.</h2>
      <p>Crie links de campanha, acompanhe cadastros e gerencie fontes em um só lugar.</p></div>
      <button type="button" className="emCaptureRefresh ds-button" disabled={loading} onClick={() => void refresh()}>
        {loading ? "Atualizando..." : "Atualizar dados"}
      </button>
    </header>

    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {info ? <p role="status">{info}</p> : null}

    <div className="emCapturePanel emCaptureCreate">
      <div className="emCapturePanelHead"><span className="emCaptureStep">01 / CRIAR</span><h3>Seu próximo link de campanha</h3><p>Escolha a página de destino e o identificador. O Mugô prepara os links para anunciar.</p></div>
      <p>Não é necessário configurar uma nova chave no Render para cada campanha. A página deve enviar
        <code> mugo_campaign </code> e <code>campaign</code> pelo App Proxy conectado.</p>
      <label className="emCaptureField">Identificador da campanha
        <input style={{display:"block",width:"100%"}} value={campaign} onChange={e=>setCampaign(normalizeSlug(e.target.value))}
          placeholder="ex: summer_drop_2027" maxLength={80}/>
      </label>
      <label className="emCaptureField">URL da landing page (https)
        <input style={{display:"block",width:"100%"}} type="url" value={landing}
          onChange={e=>setLanding(e.target.value)} placeholder="https://loja.com/pages/campanha"/>
      </label>
      {campaigns.length ? <label className="emCaptureSelectLabel">Campanhas já recebidas
        <select value="" onChange={e=>{if(e.target.value)setCampaign(e.target.value)}}>
          <option value="">Selecionar campanha...</option>
          {campaigns.map(item=><option key={item.key} value={item.key}>{item.key} ({item.leads} cadastros)</option>)}
        </select>
      </label> : null}
      {!safeCampaign ? <p role="alert">Informe um identificador com letras minúsculas, números, hífen ou _.</p> : null}
      {links.instagram ? <div className="emCaptureLinkGrid">
        <div className="emCaptureLink"><strong>Instagram</strong><p style={{overflowWrap:"anywhere",fontSize:12}}>{links.instagram}</p>
          <button type="button" onClick={()=>void copy(links.instagram!)}>Copiar link Instagram</button></div>
        <div className="emCaptureLink"><strong>Facebook</strong><p style={{overflowWrap:"anywhere",fontSize:12}}>{links.facebook}</p>
          <button type="button" onClick={()=>void copy(links.facebook!)}>Copiar link Facebook</button></div>
        <div className="emCaptureLink emCaptureLinkWide"><strong>Meta Ads — Parâmetros dinâmicos</strong>
          <p style={{overflowWrap:"anywhere",fontSize:12}}>{metaParams}</p>
          <button type="button" onClick={()=>void copy(metaParams)}>Copiar parâmetros da Meta</button>
        </div>
        <p style={{fontSize:12}}>A origem, mídia e campanha são armazenadas na captação.
          Identificadores de anúncio e posicionamento requerem extensão do schema antes de aparecer no Mugô.</p>
      </div> : <p>Informe um link HTTP(S) válido e um identificador para gerar os links.</p>}
      <p><strong>Importante:</strong> gerar o link não publica nem agenda uma campanha. Ela aparece no histórico após o primeiro cadastro confirmado.</p>
    </div>

    <div className="emCapturePanel emCaptureSources">
      <div className="emCapturePanelHead"><span className="emCaptureStep">02 / CONEXÕES</span><h3>Fontes de captação</h3><p>Conecte uma vez, use em quantas campanhas precisar.</p></div>
      <p>Uma fonte Shopify conectada pode servir várias campanhas. Uma nova fonte só é necessária
        ao conectar um canal externo diferente.</p>
      {sources.length ? <div className="emTableWrap"><table className="emTable"><thead><tr><th>Fonte</th><th>Tipo</th><th>Situação</th></tr></thead><tbody>
        {sources.map(source=><tr key={source.id}><td>{source.name}</td><td>{source.kind}</td>
          <td>{source.active ? "Ativa" : "Desativada"}</td></tr>)}
      </tbody></table></div> : <p>Nenhuma fonte cadastrada ainda. Shopify poderá provisionar a fonte ao receber um cadastro assinado da loja conectada.</p>}
      {canEdit ? <div className="emCaptureConnect">
        <h4>Conectar outra fonte externa</h4>
        <label>Nome<input value={sourceName} onChange={e=>setSourceName(e.target.value)} maxLength={100}/></label>
        <label>Tipo<select value={sourceKind} onChange={e=>setSourceKind(e.target.value)}>
          <option value="custom_form">Formulário externo</option>
          <option value="shopify">Shopify</option>
          <option value="woocommerce">WooCommerce</option>
          <option value="vtex">VTEX</option>
        </select></label>
        <button type="button" onClick={()=>void createSource()} disabled={creating || !sourceName.trim()}>
          {creating ? "Criando..." : "Criar fonte"}
        </button>
        {issuedKey ? <div role="status" style={{border:"1px solid #dbe0e5",padding:12,borderRadius:8}}>
          <strong>Credencial gerada — exibida apenas agora</strong>
          <p>ID: <code>{issuedKey.id}</code></p>
          <p>Chave: <code style={{overflowWrap:"anywhere"}}>{issuedKey.key}</code></p>
          <button type="button" onClick={()=>void copy(issuedKey.key)}>Copiar chave privada</button>
          <button type="button" onClick={()=>setIssuedKey(null)}>Já guardei a chave</button>
          <p>Não inclua a chave no HTML, em anúncios ou no navegador do visitante.</p>
        </div> : null}
      </div> : null}
    </div>

    <div className="emCapturePanel emCaptureResults">
      <div className="emCapturePanelHead"><span className="emCaptureStep">03 / RESULTADOS</span><h3>Desempenho da captação</h3><p>{safeCampaign || "Selecione uma campanha para acompanhar os resultados."}</p></div>
      {summary ? <>
        <div className="emCaptureStats">
          <Stat label="Cadastros" value={summary.total}/><Stat label="Contatos únicos" value={summary.unique}/>
          <Stat label="Aceites e-mail declarados" value={summary.email_opt_in_claimed}/>
          <Stat label="Aceites WhatsApp declarados" value={summary.whatsapp_opt_in_claimed}/>
          <Stat label="Consentimentos pendentes" value={summary.pending_validation}/>
        </div>
        <p><strong>Captura não autoriza disparos.</strong> Os consentimentos declarados precisam de validação e
          todas as regras de opt-out continuam aplicáveis.</p>
        <h4>Origem</h4>
        {summary.sources.length ? <table><thead><tr><th>UTM</th><th>Cadastros</th></tr></thead><tbody>
          {summary.sources.map(s=><tr key={s.source}><td>{s.source}</td><td>{s.leads}</td></tr>)}
        </tbody></table> : <p>Sem cadastros nesta campanha.</p>}
        {canEdit && recent.length ? <>
          <h4>Contatos recentes</h4>
          <table><thead><tr><th>Nome</th><th>E-mail</th><th>Telefone</th><th>Origem</th></tr></thead><tbody>
            {recent.map(item=><tr key={item.id}><td>{item.name}</td><td>{item.email_masked}</td>
              <td>{item.phone_masked}</td><td>{item.utm_source}</td></tr>)}
          </tbody></table>
        </> : null}
      </> : <p>Selecione uma campanha para consultar os resultados.</p>}
    </div>
    <GroupInviteCampaigns campaign={safeCampaign} canEdit={canEdit} leads={summary?.total ?? null} />
  </section>;
}
