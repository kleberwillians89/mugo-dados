import type { MetaPlacements } from "../../app/metaAds";
import { DEFAULT_META_PLACEMENTS } from "./metaPlacements";

type Props = { value: MetaPlacements; onChange: (value: MetaPlacements) => void; disabled?: boolean };
type Channel = MetaPlacements["platforms"][number];
/** Posicionamentos manuais com os nomes do Gerenciador (valores da API da Meta). */
const CHANNELS: { key: Channel; name: string; positions: { key: string; name: string; description: string }[] }[] = [
  { key: "facebook", name: "Facebook", positions: [
    { key: "feed", name: "Feed do Facebook", description: "Feed principal" },
    { key: "profile_feed", name: "Feed do perfil do Facebook", description: "Perfis" },
    { key: "marketplace", name: "Marketplace do Facebook", description: "Página inicial e navegação" },
    { key: "video_feeds", name: "Feeds de vídeo do Facebook", description: "Vídeo e Watch" },
    { key: "right_hand_column", name: "Coluna da direita do Facebook", description: "Computador" },
    { key: "story", name: "Stories do Facebook", description: "Tela cheia vertical" },
    { key: "facebook_reels", name: "Reels do Facebook", description: "Vídeos verticais" },
    { key: "instream_video", name: "Vídeos in-stream do Facebook", description: "Dentro de vídeos" },
    { key: "search", name: "Resultados da pesquisa do Facebook", description: "Pesquisa" },
    { key: "notification", name: "Notificações do Facebook", description: "Notificações" },
  ] },
  { key: "instagram", name: "Instagram", positions: [
    { key: "stream", name: "Feed do Instagram", description: "Publicações no feed" },
    { key: "profile_feed", name: "Feed do perfil do Instagram", description: "Perfis" },
    { key: "explore", name: "Explorar do Instagram", description: "Ao abrir uma publicação" },
    { key: "explore_home", name: "Página inicial do Explorar do Instagram", description: "Grade do Explorar" },
    { key: "story", name: "Stories do Instagram", description: "Tela cheia vertical" },
    { key: "reels", name: "Reels do Instagram", description: "Vídeos verticais" },
    { key: "ig_search", name: "Resultados da pesquisa do Instagram", description: "Pesquisa" },
  ] },
  { key: "messenger", name: "Messenger", positions: [
    { key: "messenger_home", name: "Caixa de entrada do Messenger", description: "Lista de conversas" },
    { key: "story", name: "Stories do Messenger", description: "Tela cheia" },
    { key: "sponsored_messages", name: "Mensagens patrocinadas do Messenger", description: "Para quem já conversou com a Página" },
  ] },
  { key: "audience_network", name: "Audience Network", positions: [
    { key: "classic", name: "Apps e sites nativos, de banner e intersticiais", description: "Fora da Meta" },
    { key: "rewarded_video", name: "Vídeos com incentivo", description: "Apps parceiros" },
  ] },
];

export default function MetaPlacementPicker({ value, onChange, disabled }: Props) {
  const p = value || DEFAULT_META_PLACEMENTS;
  const patch = (changes: Partial<MetaPlacements>) => onChange({...p, ...changes});
  const list = (channel: Channel) => (p[channel] || []) as string[];
  const platform = (name: Channel, enabled: boolean) => {
    const platforms = enabled ? [...p.platforms, name] : p.platforms.filter(x => x !== name);
    const extra = enabled && !list(name).length ? { [name]: CHANNELS.find((c) => c.key === name)!.positions.slice(0, 1).map((x) => x.key) } : {};
    patch({platforms: [...new Set(platforms)], ...extra} as Partial<MetaPlacements>);
  };
  const position = (channel: Channel, key: string, enabled: boolean) => {
    const values = list(channel);
    patch({[channel]: enabled ? [...values, key] : values.filter(x => x !== key)} as Partial<MetaPlacements>);
  };
  return <section className="metaPlacement" aria-label="Canais e posicionamentos da campanha">
    <div className="metaPlacementHeader"><h3>Posicionamentos</h3>
      <p>Como no Gerenciador: deixe a Meta escolher (Advantage+) ou escolha manualmente onde o anúncio aparece.</p></div>
    <div className="metaPlacementMode">
      <label><input type="radio" name="meta-placement-mode" disabled={disabled} checked={p.mode === "automatic"}
        onChange={() => patch({mode:"automatic"})}/> Posicionamentos Advantage+</label>
      <label><input type="radio" name="meta-placement-mode" disabled={disabled} checked={p.mode === "manual"}
        onChange={() => patch({mode:"manual"})}/> Posicionamentos manuais</label>
    </div>
    {p.mode === "automatic" ? <p className="ds-caption">A Meta distribui o orçamento entre os posicionamentos onde o anúncio tende a ter melhor desempenho.</p> :
      <div className="metaPlacementGrid">
        {CHANNELS.map((channel) => <div key={channel.key} className="metaPlacementChannel">
          <label className="metaPlacementChannelTitle"><input type="checkbox" disabled={disabled}
            checked={p.platforms.includes(channel.key)}
            onChange={e => platform(channel.key, e.target.checked)}/>
            <strong>{channel.name}</strong></label>
          {p.platforms.includes(channel.key) ? <div className="metaPlacementPositions">
            {channel.positions.map(pos => <label key={pos.key}><input type="checkbox" disabled={disabled}
              checked={list(channel.key).includes(pos.key)}
              onChange={e => position(channel.key, pos.key, e.target.checked)}/>
              <span><b>{pos.name}</b><small>{pos.description}</small></span></label>)}
          </div> : <p className="ds-caption">Este canal não receberá o anúncio.</p>}
        </div>)}
      </div>}
    {p.mode === "manual" && (!p.platforms.length || p.platforms.some(x => !list(x).length)) ?
      <p className="studioError" role="alert">Selecione pelo menos um canal e um posicionamento em cada canal ativo.</p> : null}
  </section>;
}
