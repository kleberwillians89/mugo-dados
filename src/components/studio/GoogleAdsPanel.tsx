import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { Brief } from "../../app/briefs";
import { getActiveClientId } from "../../app/activeClient";
import {
  createGoogleCampaignDraft, deleteGoogleCampaignDraft, listGoogleCampaignDrafts,
  getGoogleCampaignPublicationContext, publishGoogleCampaignDraft, updateGoogleCampaignDraft,
  type GoogleCampaignDraft, type GoogleCampaignPayload,
} from "../../app/googleCampaignDrafts";
import Drawer from "../Drawer";
import "./googleAdsPanel.css";

const today = () => new Date().toISOString().slice(0, 10);
const later = () => { const d = new Date(); d.setDate(d.getDate() + 14); return d.toISOString().slice(0, 10); };
const blank = (): GoogleCampaignPayload => ({
  platform: "google_ads", name: "", objective: "vendas", type: "SEARCH",
  daily_budget: 30, start_date: today(), end_date: later(), final_url: "",
  locations: [], keywords: [], headlines: [], descriptions: [], notes: "",
  networks: {google_search: true,search_partners:false,display_network:false},
  contains_eu_political_advertising: null,
});
const splitLines = (text: string) => text.split("\n").map((s) => s.trim()).filter(Boolean);
const friendlyError = (cause: unknown) => cause instanceof Error ? cause.message : "Não foi possível salvar a campanha.";

export type GooglePrepareRequest = { nonce: number; brief: Brief } | null;
function fromBrief(brief: Brief): GoogleCampaignPayload {
  const base = blank();
  const detail = brief.brief;
  const raw = String(detail.media?.objective || detail.objective || "").toLowerCase();
  const objective: GoogleCampaignPayload["objective"] = raw.includes("lead") || raw.includes("cadastro") ? "leads"
    : raw.includes("tráfego") || raw.includes("trafego") ? "trafego" : "vendas";
  const validDeadline = detail.deadline?.slice(0, 10) || "";
  const endDate = /^\d{4}-\d{2}-\d{2}$/.test(validDeadline) && validDeadline >= base.start_date
    ? validDeadline : base.end_date;
  const days = Math.max(1, Math.round((new Date(endDate + "T12:00:00").getTime() -
    new Date(base.start_date + "T12:00:00").getTime()) / 86_400_000) + 1);
  const dailyBudget = detail.media?.budget && detail.media.budget > 0
    ? Math.max(6, Math.round(detail.media.budget / days * 100) / 100) : base.daily_budget;
  return { ...base, name: detail.title.slice(0, 120), objective, daily_budget: dailyBudget, end_date: endDate,
    notes: ["Briefing: " + brief.id, detail.summary, detail.key_message && "Mensagem: " + detail.key_message,
      detail.audience && "Público: " + detail.audience, detail.goal && "Meta: " + detail.goal,
      detail.media?.budget ? "Verba total informada: R$ " + detail.media.budget : "",
      "Revise datas, orçamento diário, URL de destino e anúncios antes de publicar.",
    ].filter(Boolean).join("\n"),
  };
}

export default function GoogleAdsPanel({ request = null }: { request?: GooglePrepareRequest }) {
  const clientId = getActiveClientId();
  const handled = useRef<number | null>(null);
  const [drafts, setDrafts] = useState<GoogleCampaignDraft[]>([]);
  const [editing, setEditing] = useState<GoogleCampaignDraft | "new" | null>(null);
  const [form, setForm] = useState<GoogleCampaignPayload>(blank);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const result = await listGoogleCampaignDrafts();
      if (getActiveClientId() === clientId) setDrafts(result.drafts);
    } catch (cause) { if (getActiveClientId() === clientId) setError(friendlyError(cause)); }
    finally { if (getActiveClientId() === clientId) setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);
  const newDraft = () => { setForm(blank()); setEditing("new"); setError(null); setNotice(null); };
  useEffect(() => {
    if (!request || request.nonce === handled.current) return;
    handled.current = request.nonce;
    setForm(fromBrief(request.brief)); setEditing("new"); setError(null); setNotice(null);
  }, [request]);
  const open = (draft: GoogleCampaignDraft) => { setForm(draft.payload); setEditing(draft); setError(null); };
  const set = (patch: Partial<GoogleCampaignPayload>) => setForm((f) => ({ ...f, ...patch }));
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim() || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = editing && editing !== "new"
        ? await updateGoogleCampaignDraft(editing.id, form)
        : await createGoogleCampaignDraft(form);
      setEditing(null); setDrafts((list) => [result.draft, ...list.filter((d) => d.id !== result.draft.id)]);
      setNotice("Rascunho salvo no Mugô Dados. Nenhum anúncio foi enviado ao Google.");
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(false); }
  }
  async function remove(draft: GoogleCampaignDraft) {
    if (!window.confirm(`Excluir o rascunho "${draft.payload.name}"?`)) return;
    setBusy(true); setError(null);
    try {
      await deleteGoogleCampaignDraft(draft.id);
      setDrafts((list) => list.filter((d) => d.id !== draft.id));
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(false); }
  }
  async function publish(draft: GoogleCampaignDraft) {
    if (busy || draft.status === "publicando" || draft.status === "publicada") return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const context = await getGoogleCampaignPublicationContext();
      const start = new Date(`${draft.payload.start_date}T12:00:00`);
      const end = new Date(`${draft.payload.end_date}T12:00:00`);
      const days = Math.max(1, Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1);
      const total = draft.payload.daily_budget * days;
      const confirmed = window.confirm(
        `Criar "${draft.payload.name}" na conta Google Ads ${context.account}?\n\n` +
        `R$ ${draft.payload.daily_budget.toLocaleString("pt-BR")} por dia · ${days} dias · até R$ ${total.toLocaleString("pt-BR")}\n` +
        `${draft.payload.start_date} a ${draft.payload.end_date}\n\n` +
        "A campanha, o grupo, as palavras-chave e o anúncio serão criados PAUSADOS. Nenhum gasto começa agora.",
      );
      if (!confirmed) return;
      const result = await publishGoogleCampaignDraft(draft.id);
      setDrafts((list) => list.map((item) => item.id === result.draft.id ? result.draft : item));
      setNotice("Campanha criada pausada no Google Ads. Revise-a antes de qualquer ativação.");
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(false); }
  }
  return <section className="ds-section googleCampaignPanel" aria-labelledby="google-ads-campaigns">
    <div className="ds-sectionHead">
      <div className="ds-sectionHeadText">
        <h2 className="ds-sectionTitle" id="google-ads-campaigns">Campanhas Google Ads</h2>
        <p className="ds-caption">Prepare campanhas de pesquisa, palavras-chave, anúncios e orçamento. Publicação pela API ainda não habilitada.</p>
      </div>
      <button type="button" className="ds-button is-primary" onClick={newDraft}>+ Nova campanha Google</button>
    </div>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {notice ? <p className="studioOk" role="status">{notice}</p> : null}
    {loading ? <p className="ds-caption">Carregando campanhas…</p> : drafts.length ? <div className="googleCampaignCards">
      {drafts.map((draft) => <article className="googleCampaignCard" key={draft.id}>
        <div><strong>{draft.payload.name}</strong><small>{draft.payload.objective} · Pesquisa · R$ {draft.payload.daily_budget.toLocaleString("pt-BR")}/dia · {draft.status}</small>
          {draft.error ? <small className="studioError">{draft.error}</small> : null}</div>
        <div className="googleCampaignCardActions">
          {draft.status === "publicada" && draft.ads_manager_url
            ? <a className="ds-button" href={draft.ads_manager_url} target="_blank" rel="noreferrer">Abrir no Google Ads</a>
            : <button type="button" className="ds-button is-primary" disabled={busy || draft.status === "publicando"} onClick={() => void publish(draft)}>
              {draft.status === "publicando" ? "Publicando…" : "Criar pausada no Google"}</button>}
          {draft.status !== "publicada" && draft.status !== "publicando" ? <>
            <button type="button" className="ds-button" disabled={busy} onClick={() => open(draft)}>Editar</button>
            <button type="button" className="ds-link" disabled={busy} onClick={() => void remove(draft)}>Excluir</button>
          </> : null}
        </div>
      </article>)}
    </div> : <p className="ds-emptyLine">Nenhuma campanha Google preparada.</p>}
    <Drawer open={Boolean(editing)} width="lg" title={editing === "new" ? "Nova campanha Google Ads" : "Editar campanha Google Ads"}
      description="Rascunho de campanha de Pesquisa. Não conecta nem publica anúncios na conta Google." onClose={() => { if (!busy) setEditing(null); }}>
      {editing ? <form className="googleCampaignForm" onSubmit={(event) => void save(event)}>
        <label>Nome da campanha<input required maxLength={120} value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="Ex.: Search — Linha Running" /></label>
        <div className="googleCampaignFormRow">
          <label>Objetivo<select value={form.objective} onChange={(e) => set({ objective: e.target.value as GoogleCampaignPayload["objective"] })}>
            <option value="vendas">Vendas</option><option value="leads">Leads</option><option value="trafego">Tráfego</option></select></label>
          <label>Orçamento por dia (R$)<input type="number" required min={6} step="0.01" value={form.daily_budget} onChange={(e) => set({ daily_budget: Number(e.target.value) })} /></label>
        </div>
        <div className="googleCampaignFormRow">
          <label>Data inicial<input type="date" required value={form.start_date} onChange={(e) => set({ start_date: e.target.value })} /></label>
          <label>Data final<input type="date" required min={form.start_date} value={form.end_date} onChange={(e) => set({ end_date: e.target.value })} /></label>
        </div>
        <fieldset className="googleCampaignNetworks">
          <legend>Redes de veiculação — Pesquisa</legend>
          <p>Escolha onde a campanha de Pesquisa poderá aparecer. Não cria campanhas Performance Max, Display nem YouTube separadas.</p>
          <label><input type="checkbox" checked disabled /> Pesquisa Google <small>(obrigatória neste formato)</small></label>
          <label><input type="checkbox" checked={Boolean(form.networks?.search_partners)}
            onChange={e => set({networks:{google_search:true,search_partners:e.target.checked,display_network:Boolean(form.networks?.display_network)}})} />
            Parceiros de pesquisa do Google</label>
          <label><input type="checkbox" checked={Boolean(form.networks?.display_network)}
            onChange={e => set({networks:{google_search:true,search_partners:Boolean(form.networks?.search_partners),display_network:e.target.checked}})} />
            Rede de Display do Google <small>(expansão opcional desta campanha de Pesquisa)</small></label>
          <div className="googleCampaignNetworkHint">Selecionado: Pesquisa Google
            {form.networks?.search_partners ? " · Parceiros de pesquisa" : ""}
            {form.networks?.display_network ? " · Rede de Display" : ""}</div>
        </fieldset>
        <label>URL final (HTTPS)<input type="url" placeholder="https://exemplo.com.br" value={form.final_url} onChange={(e) => set({ final_url: e.target.value })} /></label>
        <label>Localizações (uma por linha)<textarea rows={2} value={form.locations.join("\n")} onChange={(e) => set({ locations: splitLines(e.target.value) })} /></label>
        <label>Palavras-chave (uma por linha)<textarea rows={4} value={form.keywords.join("\n")} onChange={(e) => set({ keywords: splitLines(e.target.value) })} placeholder={"tênis de corrida\ntênis para caminhada"} /></label>
        <label>Títulos dos anúncios (até 15, 30 caracteres cada)<textarea rows={4} value={form.headlines.join("\n")} onChange={(e) => set({ headlines: splitLines(e.target.value) })} /></label>
        <label>Descrições (até 4, 90 caracteres cada)<textarea rows={3} value={form.descriptions.join("\n")} onChange={(e) => set({ descriptions: splitLines(e.target.value) })} /></label>
        <label>Publicidade política na União Europeia<select required value={form.contains_eu_political_advertising === null ? "" : String(form.contains_eu_political_advertising)}
          onChange={(e) => set({ contains_eu_political_advertising: e.target.value === "" ? null : e.target.value === "true" })}>
          <option value="">Selecione para confirmar</option><option value="false">Não contém</option><option value="true">Contém</option>
        </select></label>
        <label>Observações<textarea rows={2} value={form.notes} onChange={(e) => set({ notes: e.target.value })} /></label>
        <p className="ds-caption">Salvar mantém apenas o planejamento. A criação no Google é uma ação separada e sempre começa pausada.</p>
        <button className="ds-button is-primary" disabled={busy || !form.name.trim()}>{busy ? "Salvando…" : "Salvar rascunho Google Ads"}</button>
      </form> : null}
    </Drawer>
  </section>;
}
