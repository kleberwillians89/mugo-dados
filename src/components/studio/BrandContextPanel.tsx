import { useEffect, useState } from "react";
import { http, clientClientPath } from "../../app/api";

type Ctx = {
  marca?: { tone_of_voice?: string; personality?: string; audience?: string; pillars?: unknown[]; keywords_use?: string[]; keywords_avoid?: string[]; restrictions?: string };
  aprendizados?: { aprovados?: { pauta?: string; pelo_cliente?: boolean }[]; ajustes_pedidos?: { pauta?: string; comentario?: string }[] };
  redacao?: { campanha: string; status: string; objetivo?: string }[];
  midia?: { plano_do_mes?: { objetivo?: string; verba?: number | null }; campanhas_em_veiculacao?: { campanha: string; recomendacao?: string }[] };
  agenda?: { data: string; pauta: string; status: string }[];
  clipping?: { manchete: string; sentimento?: string | null }[];
  lacunas?: string[];
};

const pillarName = (p: unknown) => (typeof p === "string" ? p : (p as { name?: string })?.name || "");

/**
 * Mesmo contexto que a IA de Calendário, Redação, Mídia On e Clipping usa (studio_intelligence),
 * para a equipe ver que tudo parte do tom, dos princípios e das campanhas da marca.
 */
export default function BrandContextPanel({ clientId }: { clientId: string }) {
  const [ctx, setCtx] = useState<Ctx | null>(null);
  useEffect(() => {
    let alive = true;
    http<Ctx>(clientClientPath("/studio/brand-context")).then((d) => { if (alive) setCtx(d); }).catch(() => { if (alive) setCtx(null); });
    return () => { alive = false; };
  }, [clientId]);
  if (!ctx) return null;
  const m = ctx.marca || {};
  const rows: [string, string][] = [
    ["Tom de voz", [m.tone_of_voice, m.personality].filter(Boolean).join(" · ")],
    ["Pilares", (m.pillars || []).map(pillarName).filter(Boolean).join(", ")],
    ["Usar / evitar", [m.keywords_use?.length ? `usar: ${m.keywords_use.slice(0, 8).join(", ")}` : "", m.keywords_avoid?.length ? `evitar: ${m.keywords_avoid.slice(0, 8).join(", ")}` : ""].filter(Boolean).join(" · ")],
    ["Restrições", m.restrictions || ""],
    ["Aprovado pelo cliente", (ctx.aprendizados?.aprovados || []).filter((a) => a.pelo_cliente).map((a) => a.pauta).filter(Boolean).slice(0, 3).join(" · ")],
    ["Ajustes pedidos", (ctx.aprendizados?.ajustes_pedidos || []).map((a) => a.comentario).filter(Boolean).slice(0, 3).join(" · ")],
    ["Redação", (ctx.redacao || []).map((c) => `${c.campanha} (${c.status})`).join(" · ")],
    ["Mídia On", [ctx.midia?.plano_do_mes?.objetivo ? `plano: ${ctx.midia.plano_do_mes.objetivo}` : "", ...(ctx.midia?.campanhas_em_veiculacao || []).slice(0, 3).map((c) => `${c.campanha}${c.recomendacao ? ` → ${c.recomendacao}` : ""}`)].filter(Boolean).join(" · ")],
    ["Próximas pautas", (ctx.agenda || []).slice(0, 4).map((a) => `${a.data.split("-").reverse().slice(0, 2).join("/")} ${a.pauta}`).join(" · ")],
    ["Clipping", (ctx.clipping || []).slice(0, 3).map((c) => c.manchete).join(" · ")],
  ];
  const filled = rows.filter(([, v]) => v);
  return <details className="brandContext">
    <summary>Contexto da marca usado pela IA <span>{filled.length} de {rows.length} fontes</span></summary>
    <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || <em>sem dado</em>}</dd></div>)}</dl>
    {ctx.lacunas?.length ? <p className="libHint">Faltando: {ctx.lacunas.join(", ")}. Preencha o perfil da marca no Calendário e o contexto de negócio em Empresas.</p> : null}
  </details>;
}
