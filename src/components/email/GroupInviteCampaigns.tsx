import { useCallback, useEffect, useState } from "react";
import { http, publicApiUrl } from "../../app/api";
import { getActiveClientId } from "../../app/activeClient";
import "./groupInviteCampaigns.css";

type GroupLink = {
  id: string; client_id: string; campaign_key: string; label: string;
  variant: "direct" | "post_signup"; slug: string; invite_url: string;
  active: boolean; click_count: number; created_at: string;
};
type Props = { campaign: string; canEdit: boolean; leads?: number | null };
const variants = [
  { value: "direct", title: "Campanha A · Direto para o grupo", hint: "O anúncio abre o convite sem cadastro." },
  { value: "post_signup", title: "Campanha B · Após cadastro", hint: "O convite aparece depois da confirmação do formulário." },
] as const;

export default function GroupInviteCampaigns({ campaign, canEdit, leads = null }: Props) {
  const clientId = getActiveClientId();
  const [links, setLinks] = useState<GroupLink[]>([]);
  const [label, setLabel] = useState("");
  const [variant, setVariant] = useState<"direct" | "post_signup">("direct");
  const [invite, setInvite] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const filtered = links.filter(item => item.campaign_key === campaign);

  const refresh = useCallback(async () => {
    if (!clientId) return;
    setLoading(true); setError("");
    try {
      const response = await http<{links:GroupLink[]}>(`/api/relationship/group-links?client_id=${encodeURIComponent(clientId)}`);
      if (getActiveClientId() === clientId) setLinks(response.links || []);
    } catch (cause) {
      if (getActiveClientId() === clientId) setError(cause instanceof Error ? cause.message : "Falha ao consultar convites.");
    } finally { if (getActiveClientId() === clientId) setLoading(false); }
  }, [clientId]);

  useEffect(() => { setLinks([]); setNote(""); void refresh(); }, [refresh]);

  async function create() {
    if (busy || !canEdit || !campaign || !label.trim() || !invite.trim()) return;
    setBusy(true); setNote(""); setError("");
    try {
      const data = await http<{link:GroupLink}>(`/api/relationship/group-links?client_id=${encodeURIComponent(clientId)}`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({campaign_key:campaign,label:label.trim(),variant,invite_url:invite.trim()}),
      });
      if (getActiveClientId() !== clientId) return;
      setLinks(current=>[data.link,...current]);
      setLabel("");
      setNote("Link rastreável criado. Não há campanha ou anúncio publicado automaticamente.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível criar o link.");
    } finally {setBusy(false);}
  }

  async function changeStatus(link: GroupLink) {
    if (!canEdit || busy) return;
    setBusy(true); setError("");
    try {
      await http(`/api/relationship/group-links/${encodeURIComponent(link.id)}/status?client_id=${encodeURIComponent(clientId)}`, {
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({active:!link.active}),
      });
      if (getActiveClientId() === clientId) setLinks(old=>old.map(x=>x.id===link.id?{...x,active:!x.active}:x));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao atualizar."); }
    finally {setBusy(false);}
  }

  async function copy(url: string) {
    try { await navigator.clipboard.writeText(url); setNote("Link copiado."); }
    catch {setError("Não foi possível copiar o link.");}
  }

  return <section className="emCapturePanel emCaptureGroup" aria-label="Campanhas com grupo WhatsApp">
    <div className="emCapturePanelHead">
      <span className="emCaptureStep">04 / GRUPO VIP</span>
      <h3>Duas jornadas. Um grupo.</h3>
      <p>Crie um link rastreável para cada caminho do anúncio e compare os cliques no convite.</p>
    </div>
    <div className="emCaptureGroupWays">
      {variants.map(v=><div key={v.value}><strong>{v.title}</strong><p>{v.hint}</p></div>)}
    </div>
    <div className="emCaptureGroupStats" aria-label="Resultados por jornada">
      <div><span>Cliques — anúncio direto</span>
        <strong>{filtered.filter(l=>l.variant==="direct").reduce((sum,l)=>sum+l.click_count,0)}</strong></div>
      <div><span>Cadastros — campanha</span><strong>{leads === null ? "—" : leads}</strong></div>
      <div><span>Cliques — após cadastro</span>
        <strong>{filtered.filter(l=>l.variant==="post_signup").reduce((sum,l)=>sum+l.click_count,0)}</strong></div>
    </div>
    <p><b>Atenção:</b> clique no convite não comprova que a pessoa entrou no grupo. Esta página não identifica participantes. As contagens não são usuários únicos e podem incluir prévias automáticas.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {note ? <p role="status">{note}</p> : null}
    {canEdit ? <div className="emCaptureGroupForm">
      <label>Nome do link<input value={label} maxLength={100} placeholder="Ex.: Ruah VIP · Black Friday" onChange={e=>setLabel(e.target.value)} /></label>
      <label>Jornada<select value={variant} onChange={e=>setVariant(e.target.value as typeof variant)}>
        {variants.map(v=><option key={v.value} value={v.value}>{v.title}</option>)}
      </select></label>
      <label>Convite oficial do grupo<input type="url" value={invite} placeholder="https://chat.whatsapp.com/..."
        onChange={e=>setInvite(e.target.value)} /></label>
      <button type="button" onClick={()=>void create()} disabled={busy || !campaign || !label.trim() || !invite.trim()}>
        {busy ? "Salvando..." : "Criar link rastreável"}
      </button>
    </div> : null}
    {loading ? <p>Carregando convites...</p> : filtered.length ? <div className="emCaptureGroupList">
      {filtered.map(link => <article key={link.id}>
        <div><span className="emCaptureStep">{link.variant === "direct" ? "ANÚNCIO DIRETO" : "DEPOIS DO CADASTRO"}</span>
          <h4>{link.label}</h4>
          <p>{link.active ? "Link ativo" : "Link desativado"} · {link.click_count} cliques no convite</p>
        </div>
        <code>{publicApiUrl(`/r/${link.slug}`)}</code>
        <div className="emCaptureGroupActions">
          <button type="button" onClick={()=>void copy(publicApiUrl(`/r/${link.slug}`))}>Copiar link</button>
          {canEdit ? <button type="button" disabled={busy} onClick={()=>void changeStatus(link)}>
            {link.active ? "Desativar" : "Reativar"}
          </button> : null}
        </div>
      </article>)}
    </div> : <p>Nenhum link criado para esta campanha. Comece escolhendo o caminho e inserindo o convite do grupo.</p>}
    <p className="ds-caption">Para a jornada com cadastro, use o segundo link apenas na confirmação de sucesso do formulário. O cadastro deve continuar passando pelo App Proxy da loja conectada.</p>
  </section>;
}
