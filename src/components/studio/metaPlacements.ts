import type { MetaPlacements } from "../../app/metaAds";

/** Posicionamentos automáticos (Instagram e Facebook, todos os lugares): o padrão de uma campanha nova. */
export const DEFAULT_META_PLACEMENTS: MetaPlacements = {
  mode: "automatic", platforms: ["instagram", "facebook"],
  instagram: ["stream", "story", "reels"], facebook: ["feed", "story", "facebook_reels"],
};
