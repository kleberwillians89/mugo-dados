import { useEffect, useState } from "react";
import { http, clientClientPath } from "../../app/api";

type Ctx = {
  marca?: { tone_of_voice?: string; personality?: string; pillars?: unknown[]; keywords_use?: string[]; keywords_avoid?: string[]; restrictions?: string };
  negocio?: Record<string, string>;
  aprendizados?: { aprovados?: { pauta?: string; pelo_cliente?: boolean }[]; ajustes_pedidos?: { comentario?: string }[] };
  campanhas_ativas?: { campanha: string; status?: string; periodo?: string }[];
  plano_de_midia?: { objetivo?: string; verba_total?: number | null; por_canal?: { canal: string }[] };
  calendario_do_mes?: { posts?: number; por_status?: Record<string, number> };
  clipping?: { noticias?: { manchete: string }[] };
  referencias_do_cliente?: { link: string; o_que_gostou?: string | null }[];
  metas_do_mes?: unknown[];
  lacunas?: string[];
};

const pillarName = (p: unknown) => (typeof p === "string" ? p : (p as { name?: string })?.name || "");
const LACUNA: Record<string, string> = {
  perfil_da_marca_vazio: "perfil da marca", contexto_do_negocio_vazio: "contexto de negócio", sem_kpis_no_periodo: "KPIs do período",
  sem_historico_de_posts: "histórico de posts", sem_metas_no_mes: "metas do mês",
};

/** O mesmo contexto que a IA de Calendário, Social Media, Mídia On e Clipping usa (studio_intelligence), visível para a equipe. */
export default function BrandContextPanel({ clientId }: { clientId: string }) {
  const [ctx, setCtx] = useState<Ctx | null>(null);
  useEffect(() => {
    let alive = true;
    setCtx(null);
    http<Ctx>(clientClientPath("/studio/brand-context")).then((d) => { if (alive) setCtx(d); }).catch(() => { if (alive) setCtx(null); });
    return () => { alive = false; };
  }, [clientId]);
  if (!ctx) return null;
  const m = ctx.marca || {};
  const status = ctx.calendario_do_mes?.por_status || {};
  const rows: [string, string][] = [
    ["Tom de voz", [m.tone_of_voice, m.personality].filter(Boolean).join(" · ")],
    ["Pilares", (m.pillars || []).map(pillarName).filter(Boolean).join(", ")],
    ["Usar / evitar", [m.keywords_use?.length ? `usar: ${m.keywords_use.slice(0, 8).join(", ")}` : "", m.keywords_avoid?.length ? `evitar: ${m.keywords_avoid.slice(0, 8).join(", ")}` : ""].filter(Boolean).join(" · ")],
    ["Restrições", m.restrictions || ""],
    ["Negócio", ctx.negocio?.segment || ctx.negocio?.product_description || ""],
    ["Aprovado pelo cliente", (ctx.aprendizados?.aprovados || []).filter((a) => a.pelo_cliente).map((a) => a.pauta).filter(Boolean).slice(0, 3).join(" · ")],
    ["Ajustes pedidos", (ctx.aprendizados?.ajustes_pedidos || []).map((a) => a.comentario).filter(Boolean).slice(0, 3).join(" · ")],
    ["Social Media", (ctx.campanhas_ativas || []).map((c) => `${c.campanha}${c.status ? ` (${c.status})` : ""}`).join(" · ")],
    ["Mídia On", ctx.plano_de_midia?.objetivo ? `${ctx.plano_de_midia.objetivo}${ctx.plano_de_midia.verba_total ? ` · verba ${ctx.plano_de_midia.verba_total.toLocaleString("pt-BR")}` : ""}` : ""],
    ["Calendário do mês", ctx.calendario_do_mes?.posts ? `${ctx.calendario_do_mes.posts} pauta(s) · ${Object.entries(status).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ")}` : ""],
    ["Referências do cliente", (ctx.referencias_do_cliente || []).map((r) => r.o_que_gostou || "link").slice(0, 3).join(" · ")],
    ["Clipping", (ctx.clipping?.noticias || []).slice(0, 3).map((c) => c.manchete).join(" · ")],
  ];
  const filled = rows.filter(([, v]) => v).length;
  const gaps = (ctx.lacunas || []).map((g) => LACUNA[g]).filter(Boolean);
  return <details className="brandContext">
    <summary>Contexto da marca usado pela IA <span>{filled} de {rows.length} fontes</span></summary>
    <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || <em>sem dado</em>}</dd></div>)}</dl>
    {gaps.length ? <p className="libHint">Faltando: {gaps.join(", ")}. Preencha o perfil da marca no Calendário e o contexto de negócio em Empresas.</p> : null}
  </details>;
}
