import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { usePeriod } from "../app/PeriodContext";
import { formatCurrency, formatInteger, formatPercentNumber } from "../app/dataFormat";
import { CRM_UNAVAILABLE_TEXT, windowOpen, type CrmMessage } from "../app/crm";
import {
  ORIGIN_COLORS, OBJECTION_LABELS, STAGE_LABELS, getWhatsAppInbox, getWhatsAppInsights, getWhatsAppMessages, isOutbound,
  type WaConversation, type WhatsAppInbox, type WhatsAppInsights,
} from "../app/whatsapp";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import PeriodSelector from "../components/data/PeriodSelector";
import KpiFigure from "../components/data/KpiFigure";
import DataNotice from "../components/data/DataNotice";
import WhatsAppNumbers from "../components/whatsapp/WhatsAppNumbers";
import "../styles/whatsapp.css";

type Filter = "all" | "ad" | "bought" | "waiting";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Todas" }, { key: "ad", label: "De anúncio" },
  { key: "bought", label: "Compraram" }, { key: "waiting", label: "Sem resposta" },
];

const money = (value: number | null | undefined) => (value == null ? "—" : formatCurrency(value));
const times = (value: number | null | undefined) => (value == null ? "—" : `${formatPercentNumber(value)}×`);

function when(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso), now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return "ontem";
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}
const fullWhen = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";

function isWaiting(conv: WaConversation) {
  return Boolean(conv.unread_count) || (!!conv.last_message && !isOutbound(conv.last_message.direction));
}

/**
 * WhatsApp da marca ativa: de onde vêm as conversas, quantas viram venda, quanto custa cada venda
 * e a caixa de entrada do número da própria marca. Números: qualquer membro da empresa.
 * Conversas: agência e admin da marca (o backend recusa os demais).
 */
export default function WhatsApp() {
  const { period } = usePeriod();
  const clientId = getActiveClientId();
  const scope = `${clientId}:${period.start}:${period.end}`;
  const [insights, setInsights] = useState<{ scope: string; data: WhatsAppInsights | null; error: boolean }>({ scope: "", data: null, error: false });
  const [inbox, setInbox] = useState<{ data: WhatsAppInbox | null; error: boolean }>({ data: null, error: false });
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [thread, setThread] = useState<{ id: string; messages: CrmMessage[]; loading: boolean; error: boolean }>({ id: "", messages: [], loading: false, error: false });

  useEffect(() => {
    if (!clientId) return;
    let alive = true;
    getWhatsAppInsights(period.start, period.end)
      .then((data) => { if (alive && getActiveClientId() === clientId) setInsights({ scope, data, error: false }); })
      .catch(() => { if (alive) setInsights({ scope, data: null, error: true }); });
    return () => { alive = false; };
  }, [clientId, period.start, period.end, scope]);

  // Só a última conversa pedida pode preencher a tela: resposta atrasada de outra é descartada.
  const wanted = useRef<string | null>(null);
  const openConversation = useCallback(async (id: string) => {
    wanted.current = id;
    setOpenId(id);
    setThread({ id, messages: [], loading: true, error: false });
    try {
      const res = await getWhatsAppMessages(id);
      if (wanted.current !== id) return;
      setThread({ id, messages: res.available ? res.messages : [], loading: false, error: !res.available });
    } catch {
      if (wanted.current === id) setThread({ id, messages: [], loading: false, error: true });
    }
  }, []);

  useEffect(() => {
    if (!clientId) return;
    let alive = true;
    getWhatsAppInbox()
      .then((data) => {
        if (!alive || getActiveClientId() !== clientId) return;
        setInbox({ data, error: false });
        const first = data.conversations[0]?.id;
        if (first && !wanted.current) void openConversation(first);
      })
      .catch(() => { if (alive) setInbox({ data: null, error: true }); });
    return () => { alive = false; };
  }, [clientId, openConversation]);

  const current = insights.scope === scope ? insights : { data: null, error: false };
  const data = current.data;
  const totals = data?.totals;
  const loading = !data && !current.error;

  const conversations = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (inbox.data?.conversations || []).filter((conv) => {
      if (filter === "ad" && conv.origin.bucket !== "ad") return false;
      if (filter === "bought" && !conv.purchase) return false;
      if (filter === "waiting" && !isWaiting(conv)) return false;
      if (!term) return true;
      return [conv.contact.name, conv.contact.phone_masked, conv.purchase?.last_order, conv.origin.label, conv.insight?.summary, ...(conv.insight?.interests || [])]
        .some((value) => String(value || "").toLowerCase().includes(term));
    });
  }, [inbox.data, filter, query]);
  const open = (inbox.data?.conversations || []).find((conv) => conv.id === openId) || null;
  const messages = thread.id === openId ? thread.messages : [];

  return (
    <Shell title="WhatsApp" variant="editorial">
      <div className="ds-page waPage" data-testid="whatsapp-page">
        <PageHeader
          company={getActiveClientName()}
          title="WhatsApp"
          dateline={<span>De onde vêm as conversas, quantas viram venda e quanto custa cada venda.</span>}
          controls={<PeriodSelector />}
        />

        {current.error ? (
          <DataNotice tone="negative" role="alert" title="WhatsApp indisponível no momento.">Tente de novo em instantes.</DataNotice>
        ) : null}
        {loading ? <p className="waMuted" role="status">Carregando as conversas do período…</p> : null}
        {data?.status === "crm_unavailable" ? (
          <DataNotice tone="warning" title="Não foi possível ler o CRM.">
            {data.reason ? CRM_UNAVAILABLE_TEXT[data.reason] : "Tente de novo em instantes."}
          </DataNotice>
        ) : null}
        {data?.status === "no_brand_number" ? (
          <DataNotice title="O WhatsApp desta marca ainda não está ligado.">
            Quando o número oficial da marca for ligado ao MUGOVERSO, as conversas, a origem de cada uma e as vendas aparecem aqui.
          </DataNotice>
        ) : null}
        <WhatsAppNumbers key={clientId || "none"} onChange={() => window.location.reload()} />

        {totals ? (
          <>
            <section className="ds-kpis waKpis" aria-label="Resumo do período">
              <KpiFigure label="Conversas novas" value={formatInteger(totals.conversations)} rawValue={totals.conversations} />
              <KpiFigure label="Viraram venda" value={formatInteger(totals.converted_conversations)} rawValue={totals.converted_conversations}
                delta={totals.conversion_rate == null ? undefined : `${formatPercentNumber(totals.conversion_rate)}% das conversas`} />
              <KpiFigure label="Receita pelo WhatsApp" value={money(totals.revenue)} rawValue={totals.revenue}
                delta={totals.share_of_store_revenue == null ? undefined : `${formatPercentNumber(totals.share_of_store_revenue)}% da receita da loja`} />
              <KpiFigure label="Custo por venda (anúncios)" value={money(totals.cost_per_sale)} rawValue={totals.cost_per_sale ?? undefined}
                delta={totals.cost_per_conversation == null ? undefined : `${money(totals.cost_per_conversation)} por conversa`} />
              <KpiFigure hero label="Retorno dos anúncios de WhatsApp" value={times(totals.ads_roas)} rawValue={totals.ads_roas ?? undefined}
                delta={totals.ads_roas == null ? undefined : `cada R$ 1 virou ${money(totals.ads_roas)}`} />
            </section>

            <section className="waCard" aria-labelledby="wa-origins">
              <div className="waCardHead">
                <h2 id="wa-origins">De onde vêm as conversas</h2>
                <span className="waMuted">conversas → vendas</span>
              </div>
              {data!.origins?.length ? (
                <>
                  <div className="waStack" role="img"
                    aria-label={data!.origins.map((row) => `${row.label} ${formatPercentNumber(row.share)}%`).join(", ")}>
                    {data!.origins.map((row) => (
                      <span key={row.key} style={{ flexGrow: Math.max(row.share, 1), background: ORIGIN_COLORS[row.key] }} />
                    ))}
                  </div>
                  <ul className="waLegend">
                    {data!.origins.map((row) => (
                      <li key={row.key}>
                        <span className="waSwatch" style={{ background: ORIGIN_COLORS[row.key] }} aria-hidden="true" />
                        <span><b>{row.label}</b><br />{formatInteger(row.conversations)} conversas · {formatInteger(row.sales)} {row.sales === 1 ? "venda" : "vendas"}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : <p className="waMuted">Nenhuma conversa nova no período.</p>}
            </section>

            <section className="waCard" aria-labelledby="wa-ads">
              <div className="waCardHead">
                <h2 id="wa-ads">Anúncios que levam ao WhatsApp</h2>
                <span className="waMuted">ordenados por vendas, não por cliques</span>
              </div>
              {data!.ads?.length ? (
                <div className="waTableWrap">
                  <table className="waTable">
                    <thead><tr>
                      <th scope="col">Anúncio</th><th scope="col">Investido</th><th scope="col">Conversas</th><th scope="col">Vendas</th>
                      <th scope="col">Avançaram</th><th scope="col">Custo/venda</th><th scope="col">Retorno</th><th scope="col">Leitura</th>
                    </tr></thead>
                    <tbody>{data!.ads.map((ad) => (
                      <tr key={ad.ad_id}>
                        <th scope="row"><b>{ad.ad_name || ad.headline || `Anúncio ${ad.ad_id}`}</b>{ad.campaign_name ? <small>{ad.campaign_name}</small> : null}</th>
                        <td>{money(ad.spend)}</td>
                        <td>{formatInteger(ad.conversations)}</td>
                        <td>{formatInteger(ad.sales)}</td>
                        <td>{ad.advanced == null ? "—" : formatInteger(ad.advanced)}{ad.top_objection ? <small>trava: {ad.top_objection.label.toLowerCase()}</small> : null}</td>
                        <td>{money(ad.cost_per_sale)}</td>
                        <td><b>{times(ad.roas)}</b></td>
                        <td>{ad.verdict ? <span className={`waPill is-${ad.verdict.code}`}>{ad.verdict.label}</span> : <span className="waMuted">Pouco gasto ainda</span>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : <p className="waMuted">Nenhuma conversa vinda de anúncio com o ID registrado no período.</p>}
              {data!.alerts?.map((alert) => (
                <p key={alert.ad_id} className="waAlert"><b>Alerta:</b> {alert.text}</p>
              ))}
            </section>

            {data!.stages?.length ? (
              <section className="waCard" aria-labelledby="wa-funnel">
                <div className="waCardHead">
                  <h2 id="wa-funnel">Onde as conversas estão</h2>
                  <span className="waMuted">leitura da IA de atendimento · {formatInteger(data!.interpreted_conversations || 0)} conversas</span>
                </div>
                <ul className="waFunnel">
                  {data!.stages.map((row) => (
                    <li key={row.key} className={`is-${row.key}`}>
                      <span className="waFunnelLabel">{row.label}</span>
                      <span className="waFunnelBar"><span style={{ width: `${Math.max(row.share, 2)}%` }} /></span>
                      <b>{formatInteger(row.count)}</b>
                    </li>
                  ))}
                </ul>
                {data!.objections?.length ? (
                  <>
                    <h3 className="waSubhead">O que trava a venda</h3>
                    <ul className="waObjections">
                      {data!.objections.slice(0, 6).map((row) => (
                        <li key={row.key}><span>{row.label}</span><b>{formatInteger(row.count)}</b></li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </section>
            ) : null}

            {data!.links?.length ? (
              <section className="waCard" aria-labelledby="wa-links">
                <div className="waCardHead"><h2 id="wa-links">Links e QR codes</h2><span className="waMuted">pelo código no texto da mensagem</span></div>
                <div className="waTableWrap">
                  <table className="waTable">
                    <thead><tr><th scope="col">Código</th><th scope="col">Conversas</th><th scope="col">Vendas</th><th scope="col">Receita</th></tr></thead>
                    <tbody>{data!.links.map((row) => (
                      <tr key={row.code}><th scope="row"><b>{row.code}</b></th><td>{formatInteger(row.conversations)}</td>
                        <td>{formatInteger(row.sales)}</td><td>{money(row.revenue)}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              </section>
            ) : null}
          </>
        ) : null}

        <section className="waCard waInbox" aria-labelledby="wa-inbox">
          <div className="waInboxList">
            <div className="waInboxTools">
              <h2 id="wa-inbox">Conversas</h2>
              <label className="waSearch">Buscar
                <input type="search" placeholder="Nome, final do telefone ou pedido" value={query} onChange={(e) => setQuery(e.target.value)} />
              </label>
              <div className="waChips" role="group" aria-label="Filtrar conversas">
                {FILTERS.map((item) => (
                  <button key={item.key} type="button" className={filter === item.key ? "is-active" : ""} aria-pressed={filter === item.key}
                    onClick={() => setFilter(item.key)}>{item.label}</button>
                ))}
              </div>
            </div>
            {inbox.error ? <p className="waMuted waPad">As conversas ficam visíveis para a agência e o admin da marca.</p> : null}
            {inbox.data && inbox.data.status !== "available" ? (
              <p className="waMuted waPad">{inbox.data.status === "crm_unavailable" && inbox.data.reason ? CRM_UNAVAILABLE_TEXT[inbox.data.reason] : "O WhatsApp desta marca ainda não está ligado no CRM."}</p>
            ) : null}
            {!inbox.data && !inbox.error ? <p className="waMuted waPad" role="status">Carregando conversas…</p> : null}
            {inbox.data?.status === "available" && !conversations.length ? <p className="waMuted waPad">Nenhuma conversa com esse filtro.</p> : null}
            <ul className="waConvList">
              {conversations.map((conv) => (
                <li key={conv.id} className={conv.id === openId ? "is-open" : ""}>
                  <button type="button" onClick={() => void openConversation(conv.id)} aria-current={conv.id === openId ? "true" : undefined}>
                    <span className="waConvTop"><b>{conv.contact.name || conv.contact.phone_masked}</b><small>{when(conv.last_message_at)}</small></span>
                    <span className="waConvPreview">
                      {conv.last_message ? `${isOutbound(conv.last_message.direction) ? (conv.attendance_mode === "bot" ? "IA: " : "Você: ") : ""}${conv.last_message.text}` : "Sem mensagens"}
                    </span>
                    <span className="waTags">
                      <span className={`waTag is-${conv.origin.bucket}`}>{conv.origin.label}</span>
                      {conv.insight ? <span className={`waTag is-stage-${conv.insight.stage}`}>{STAGE_LABELS[conv.insight.stage] || conv.insight.stage}</span> : null}
                      {conv.purchase ? <span className="waTag is-bought">Comprou {money(conv.purchase.revenue)}</span> : null}
                      {!conv.purchase && isWaiting(conv) ? <span className="waTag is-waiting">Aguardando resposta</span> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="waThread">
            {open ? (
              <>
                <header className="waThreadHead">
                  <div><b>{open.contact.name || "Contato"}</b><small>{open.contact.phone_masked}{open.attendance_mode === "bot" ? " · atendida pela IA" : ""}</small></div>
                  <span className={windowOpen(open.service_window_expires_at) ? "waTag is-bought" : "waTag"}>
                    {windowOpen(open.service_window_expires_at) ? "Janela de 24h aberta" : "Fora da janela de 24h"}
                  </span>
                </header>
                <ol className="waMessages">
                  {open.origin.bucket === "ad" ? <li className="waEvent">Veio do anúncio{open.origin.ad_headline ? ` “${open.origin.ad_headline}”` : ""}</li> : null}
                  {open.origin.bucket === "link" ? <li className="waEvent">Veio do link {open.origin.entry_code}</li> : null}
                  {thread.loading ? <li className="waEvent is-plain">Carregando…</li> : null}
                  {thread.error ? <li className="waEvent is-plain">Não foi possível abrir esta conversa agora.</li> : null}
                  {messages.map((m) => (
                    <li key={m.id} className={`waBubble${isOutbound(m.direction) ? " is-out" : ""}${m.failed ? " is-failed" : ""}`}>
                      <p>{m.text || (m.template_name ? `Modelo: ${m.template_name}` : `[${m.type}]`)}</p>
                      <small>{fullWhen(m.at)}{isOutbound(m.direction) && m.read_at ? " · lida" : ""}{m.failed ? " · falhou" : ""}</small>
                    </li>
                  ))}
                  {open.purchase ? (
                    <li className="waEvent is-sale">
                      {open.purchase.last_order?.startsWith("#") ? `Pedido ${open.purchase.last_order} na loja` : "Venda registrada no CRM"} · {money(open.purchase.revenue)}
                    </li>
                  ) : null}
                </ol>
              </>
            ) : <p className="waMuted waPad">Escolha uma conversa.</p>}
          </div>

          <aside className="waJourney" aria-label="Origem desta conversa">
            <h3>{open?.purchase ? "Como essa venda aconteceu" : "Origem desta conversa"}</h3>
            {open ? (
              <ol className="waSteps">
                <li><span>1</span><div><b>{open.origin.bucket === "ad" ? "Viu o anúncio" : open.origin.bucket === "link" ? "Usou o link ou QR" : "Chegou ao WhatsApp"}</b>
                  <small>{open.origin.ad_headline || open.origin.entry_code || open.origin.label}</small></div></li>
                <li><span>2</span><div><b>Chamou no WhatsApp</b><small>{fullWhen(open.contact.first_seen_at) || "—"}</small></div></li>
                <li className={open.purchase ? "is-done" : "is-pending"}><span>3</span><div><b>{open.purchase ? "Comprou" : "Ainda não comprou"}</b>
                  <small>{open.purchase ? `${open.purchase.orders} ${open.purchase.orders === 1 ? "pedido" : "pedidos"} · ${money(open.purchase.revenue)}` : "nenhum pedido com este telefone"}</small></div></li>
              </ol>
            ) : null}
            {open?.insight ? (
              <div className="waInsight" aria-label="Leitura da IA">
                <h3>Leitura da IA</h3>
                <p><span className={`waTag is-stage-${open.insight.stage}`}>{STAGE_LABELS[open.insight.stage] || open.insight.stage}</span></p>
                {open.insight.summary ? <p>{open.insight.summary}</p> : null}
                {open.insight.interests.length ? <p><b>Interesses:</b> {open.insight.interests.join(", ")}</p> : null}
                {open.insight.objections.length ? <p><b>Trava:</b> {open.insight.objections.map((key) => OBJECTION_LABELS[key] || key).join(", ")}</p> : null}
                {open.insight.next_step ? <p><b>Próximo passo:</b> {open.insight.next_step}</p> : null}
                {open.insight.updated_at ? <p className="waMuted waSmall">Atualizada {fullWhen(open.insight.updated_at)}</p> : null}
              </div>
            ) : null}
            {data?.attribution_label ? <p className="waMuted waSmall">{data.attribution_label}</p> : null}
          </aside>
        </section>

        {data?.notes?.length ? <ul className="waNotes">{data.notes.slice(1).map((note) => <li key={note}>{note}</li>)}</ul> : null}
      </div>
    </Shell>
  );
}
