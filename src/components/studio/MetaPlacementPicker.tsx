import type { MetaPlacements } from "../../app/metaAds";

type Props = { value: MetaPlacements; onChange: (value: MetaPlacements) => void; disabled?: boolean };
const INSTAGRAM = [
  { key: "stream", name: "Feed do Instagram", description: "Publicações no feed" },
  { key: "story", name: "Stories", description: "Tela cheia vertical" },
  { key: "reels", name: "Reels", description: "Vídeos e anúncios verticais" },
] as const;
const FACEBOOK = [
  { key: "feed", name: "Feed do Facebook", description: "Feed principal" },
  { key: "story", name: "Stories do Facebook", description: "Tela cheia" },
  { key: "facebook_reels", name: "Reels do Facebook", description: "Vídeos verticais" },
] as const;
export const DEFAULT_META_PLACEMENTS: MetaPlacements = {
  mode: "automatic", platforms: ["instagram", "facebook"],
  instagram: ["stream", "story", "reels"], facebook: ["feed", "story", "facebook_reels"],
};
export default function MetaPlacementPicker({ value, onChange, disabled }: Props) {
  const p = value || DEFAULT_META_PLACEMENTS;
  const patch = (changes: Partial<MetaPlacements>) => onChange({...p, ...changes});
  const platform = (name: "instagram" | "facebook", enabled: boolean) => {
    const platforms = enabled ? [...p.platforms, name] : p.platforms.filter(x => x !== name);
    patch({platforms: [...new Set(platforms)]});
  };
  const position = (channel: "instagram" | "facebook", key: string, enabled: boolean) => {
    const values = p[channel] as string[];
    patch({[channel]: enabled ? [...values, key] : values.filter(x => x !== key)} as Partial<MetaPlacements>);
  };
  return <section className="metaPlacement" aria-label="Canais e posicionamentos da campanha">
    <div className="metaPlacementHeader"><h3>Onde esta campanha aparecerá?</h3>
      <p>Escolha somente os canais em que a marca anuncia. A seleção será enviada ao conjunto de anúncios na Meta.</p></div>
    <div className="metaPlacementMode">
      <label><input type="radio" name="meta-placement-mode" disabled={disabled} checked={p.mode === "automatic"}
        onChange={() => patch({mode:"automatic"})}/> Automático (Advantage+)</label>
      <label><input type="radio" name="meta-placement-mode" disabled={disabled} checked={p.mode === "manual"}
        onChange={() => patch({mode:"manual"})}/> Escolher canais e formatos</label>
    </div>
    {p.mode === "automatic" ? <p className="ds-caption">O Meta selecionará os posicionamentos. Para publicar somente no Instagram, escolha “Escolher canais e formatos”.</p> :
      <div className="metaPlacementGrid">
        {([["instagram", INSTAGRAM], ["facebook", FACEBOOK]] as const).map(([name, positions]) => <div key={name} className="metaPlacementChannel">
          <label className="metaPlacementChannelTitle"><input type="checkbox" disabled={disabled}
            checked={p.platforms.includes(name)}
            onChange={e => platform(name,e.target.checked)}/>
            <strong>{name === "instagram" ? "Instagram" : "Facebook"}</strong></label>
          {p.platforms.includes(name) ? <div className="metaPlacementPositions">
            {positions.map(pos => <label key={pos.key}><input type="checkbox" disabled={disabled}
              checked={p[name].includes(pos.key as never)}
              onChange={e => position(name,pos.key,e.target.checked)}/>
              <span><b>{pos.name}</b><small>{pos.description}</small></span></label>)}
          </div> : <p className="ds-caption">Este canal não receberá o anúncio.</p>}
        </div>)}
      </div>}
    {p.mode === "manual" && (!p.platforms.length || p.platforms.some(x=>!p[x].length)) ?
      <p className="studioError" role="alert">Selecione pelo menos um canal e um posicionamento em cada canal ativo.</p> : null}
  </section>;
}
