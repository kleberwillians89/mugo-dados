import { useEffect, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { getChannels, type Channel, type ChannelTotals } from "../app/channels";
import { usePeriod } from "../app/PeriodContext";
import { getPathForRoute } from "../app/routes";
import { formatCurrency, formatInteger } from "../app/dataFormat";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import PeriodSelector from "../components/data/PeriodSelector";
import KpiFigure from "../components/data/KpiFigure";
import PageSkeleton from "../components/data/PageSkeleton";
import "../styles/channels.css";

const num = (v: number | string | null | undefined) => (v == null || v === "" ? "—" : formatInteger(Number(v)));

function NotConnected({ channel }: { channel?: Channel }) {
  const waiting = channel && !channel.app_configured;
  return <p className="chMuted">{waiting ? "Aguardando o app da plataforma ser aprovado." : "Ainda não conectado."}{" "}
    <a href={getPathForRoute("integrations")}>Ver em Integrações</a></p>;
}

function Paid({ label, m, channel }: { label: string; m?: ChannelTotals; channel?: Channel }) {
  return <section className="chCard" aria-label={label}>
    <h3>{label}</h3>
    {!m ? <NotConnected channel={channel} /> : <>
      <div className="ds-kpis">
        <KpiFigure label="Investimento" value={formatCurrency(m.spend)} rawValue={m.spend} />
        <KpiFigure label="Impressões" value={num(m.impressions)} />
        <KpiFigure label="Cliques" value={num(m.clicks)} />
        <KpiFigure label="Conversões" value={num(m.conversions)} />
      </div>
      {m.top.length ? <ol className="chTop">{m.top.map((t) => <li key={String(t.name)}><span>{t.name || "Campanha"}</span><b>{formatCurrency(t.value)}</b></li>)}</ol> : null}
    </>}
  </section>;
}

export type Network = "tiktok" | "pinterest" | "linkedin";
const NETWORK_NAME: Record<Network, string> = { tiktok: "TikTok", pinterest: "Pinterest", linkedin: "LinkedIn" };

/** TikTok, Pinterest e LinkedIn: anúncios e orgânico da marca, no período do calendário (o mesmo das outras telas).
 *  Com ``network`` vira a aba daquela rede (como a Meta); sem ele mostra as três (link antigo /canais). */
export default function ChannelsPage({ network }: { network?: Network } = {}) {
  const { period } = usePeriod();
  const clientId = getActiveClientId();
  const [state, setState] = useState<{ key: string; rows: Channel[] | null; error: string | null }>({ key: "", rows: null, error: null });
  const key = `${clientId}|${period.start}|${period.end}`;
  const { start, end } = period;
  useEffect(() => {
    let alive = true;
    getChannels({ start, end }).then((r) => { if (alive) setState({ key, rows: r.channels, error: null }); })
      .catch((e) => { if (alive) setState({ key, rows: null, error: e instanceof Error ? e.message : "Não foi possível ler os canais." }); });
    return () => { alive = false; };
  }, [key, start, end]);

  const loading = state.key !== key;
  const by = (p: Channel["provider"]) => state.rows?.find((c) => c.provider === p);
  const tiktok = by("tiktok")?.metrics.tiktok;
  const pin = by("pinterest")?.metrics.pinterest;
  const li = by("linkedin")?.metrics.linkedin;
  const show = (n: Network) => !network || network === n;
  const title = network ? NETWORK_NAME[network] : "TikTok, Pinterest e LinkedIn";

  return <Shell title={title} variant="editorial"><div className="ds-page chPage">
    <PageHeader company={getActiveClientName() || "Empresa"} title={title} controls={<PeriodSelector />} />
    {state.error ? <p role="alert" className="chError">{state.error}</p> : null}
    {loading ? <PageSkeleton label={`Carregando ${network ? NETWORK_NAME[network] : "os canais"}…`} /> : state.rows ? <>
      {/* Um bloco por canal, com anúncios e orgânico lado a lado. */}
      {show("tiktok") ? <section className="chChannel" aria-label="TikTok">
        {!network ? <h2 className="chSection">TikTok</h2> : null}
        <div className="chGrid">
          <Paid label="Anúncios" m={by("tiktok_ads")?.metrics.tiktok_ads} channel={by("tiktok_ads")} />
          <section className="chCard" aria-label="TikTok orgânico"><h3>Orgânico</h3>
            {!tiktok ? <NotConnected channel={by("tiktok")} /> : <>
              <div className="ds-kpis">
                <KpiFigure label="Seguidores" value={num(tiktok.latest?.followers)} />
                <KpiFigure label="Curtidas" value={num(tiktok.latest?.likes)} />
                <KpiFigure label="Vídeos" value={num(tiktok.latest?.videos)} />
              </div>
              {tiktok.top.length ? <ol className="chTop">{tiktok.top.map((t) => <li key={String(t.name)}><span>{t.name || "Vídeo"}</span><b>{num(t.value)} visualizações</b></li>)}</ol> : null}
            </>}
          </section>
        </div>
      </section> : null}
      {show("pinterest") ? <section className="chChannel" aria-label="Pinterest">
        {!network ? <h2 className="chSection">Pinterest</h2> : null}
        <div className="chGrid">
          <Paid label="Anúncios" m={by("pinterest")?.metrics.pinterest_ads} channel={by("pinterest")} />
          <section className="chCard" aria-label="Pinterest orgânico"><h3>Orgânico</h3>
            {!pin ? <NotConnected channel={by("pinterest")} /> : <div className="ds-kpis">
              <KpiFigure label="Impressões" value={num(pin.impressions)} />
              <KpiFigure label="Salvamentos" value={num(pin.sums?.saves)} />
              <KpiFigure label="Cliques para o site" value={num(pin.clicks)} />
            </div>}
          </section>
        </div>
      </section> : null}
      {show("linkedin") ? <section className="chChannel" aria-label="LinkedIn">
        {!network ? <h2 className="chSection">LinkedIn</h2> : null}
        <div className="chGrid">
          <Paid label="Anúncios" m={by("linkedin")?.metrics.linkedin_ads} channel={by("linkedin")} />
          <section className="chCard" aria-label="LinkedIn página"><h3>Página (orgânico)</h3>
            {!li ? <NotConnected channel={by("linkedin")} /> : <div className="ds-kpis">
              <KpiFigure label="Seguidores" value={num(li.latest?.followers)} />
              <KpiFigure label="Impressões" value={num(li.impressions)} />
              <KpiFigure label="Cliques" value={num(li.clicks)} />
              <KpiFigure label="Curtidas" value={num(li.sums?.likes)} />
            </div>}
          </section>
        </div>
      </section> : null}
      <p className="chMuted">Instagram e Facebook continuam em Mídia → Meta. Os números seguem o período escolhido no calendário acima.</p>
    </> : null}
  </div></Shell>;
}
