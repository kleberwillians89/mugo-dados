import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Drawer from "../Drawer";
import { getBrandProfile, STUDIO_FORMATS, type StudioFormat } from "../../app/studio";
import { getActiveClientId } from "../../app/activeClient";
import {
  PLATFORM_FORMATS, PLATFORM_LABEL, PLATFORM_ORDER, WEEKDAY_LABEL, archiveMatrix, createMatrix, getMatrix, listMatrices,
  matrixToCalendar, refineOpportunity, setOpportunitiesStatus, updateOpportunity,
  type ContentMatrix as Matrix, type MatrixRequest, type MatrixSummary, type Opportunity, type OpportunityPatch, type Platform,
} from "../../app/contentOps";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

function nextMonday(): string {
  const d = new Date();
  d.setDate(d.getDate() + (((8 - d.getDay()) % 7) || 7));
  return isoDay(d);
}

/** "16/11 a 22/11" da semana N a partir da segunda inicial. */
function weekRange(weekStart: string, week: number): string {
  const [y, m, d] = weekStart.slice(0, 10).split("-").map(Number);
  const first = new Date(y, m - 1, d + 7 * (week - 1));
  const last = new Date(y, m - 1, d + 7 * (week - 1) + 6);
  return `${pad(first.getDate())}/${pad(first.getMonth() + 1)} a ${pad(last.getDate())}/${pad(last.getMonth() + 1)}`;
}

type Props = {
  canManage: boolean;
  /** Abre o Calendário depois de exportar (opcional). */
  onOpenCalendar?: () => void;
};

/**
 * Matriz de Conteúdo (trazida da iAgência): a IA sugere oportunidades por plataforma, pilar e 4 semanas,
 * a partir dos pilares do Perfil de Marca e do contexto da marca. A equipe edita, refina, seleciona e
 * descarta; as selecionadas vão para o Calendário como rascunho e seguem a aprovação de sempre.
 */
export default function ContentMatrix({ canManage, onOpenCalendar }: Props) {
  const clientId = getActiveClientId();
  const [list, setList] = useState<MatrixSummary[]>([]);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [pillars, setPillars] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState<MatrixRequest | null>(null);
  const [platform, setPlatform] = useState<Platform | "todas">("todas");
  const [showDiscarded, setShowDiscarded] = useState(false);
  const [editing, setEditing] = useState<Opportunity | null>(null);

  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, fallback: string): Promise<T | null> => {
    setBusy(key); setError(null); setNotice(null);
    try { return await fn(); } catch (cause) { setError(message(cause, fallback)); return null; } finally { setBusy(null); }
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [data, profile] = await Promise.all([listMatrices(), getBrandProfile().catch(() => null)]);
      if (getActiveClientId() !== clientId) return;
      setList(data.matrices || []);
      setPillars((profile?.profile.pillars || []).map((p) => p.name).filter(Boolean));
      if (data.matrices?.[0]) setMatrix((await getMatrix(data.matrices[0].id)).matrix);
    } catch (cause) { setError(message(cause, "Não foi possível carregar a matriz.")); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  const replace = (op: Opportunity) => setMatrix((m) => (m ? { ...m, opportunities: m.opportunities.map((o) => (o.id === op.id ? op : o)) } : m));

  async function generate(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    const r = await run("generate", () => createMatrix(form), "Não foi possível gerar a matriz.");
    if (r) {
      setForm(null); setMatrix(r.matrix); setPlatform("todas");
      setList((l) => [r.matrix, ...l.filter((x) => x.id !== r.matrix.id)]);
    }
  }

  async function open(id: string) {
    const r = await run(`open:${id}`, () => getMatrix(id), "Não foi possível abrir a matriz.");
    if (r) { setMatrix(r.matrix); setPlatform("todas"); }
  }

  async function setStatus(op: Opportunity, status: "sugerida" | "selecionada" | "descartada") {
    const r = await run(`s:${op.id}`, () => updateOpportunity(op.matrix_id, op.id, { status }), "Não foi possível atualizar.");
    if (r) replace(r.opportunity);
  }

  const visible = useMemo(() => (matrix?.opportunities || []).filter((o) =>
    (platform === "todas" || o.platform === platform) && (showDiscarded || o.status !== "descartada")), [matrix, platform, showDiscarded]);
  const selected = (matrix?.opportunities || []).filter((o) => o.status === "selecionada");
  const exported = (matrix?.opportunities || []).filter((o) => o.status === "exportada").length;
  const discarded = (matrix?.opportunities || []).filter((o) => o.status === "descartada").length;
  const rows = useMemo(() => {
    const names = [...(matrix?.pillars || []).map((p) => p.name), ...visible.map((o) => o.pillar)];
    return [...new Set(names)].filter((name) => visible.some((o) => o.pillar === name));
  }, [matrix, visible]);

  async function selectVisible() {
    if (!matrix) return;
    const ids = visible.filter((o) => o.status === "sugerida").map((o) => o.id);
    if (!ids.length) return;
    const r = await run("bulk", () => setOpportunitiesStatus(matrix.id, ids, "selecionada"), "Não foi possível selecionar.");
    if (r) setMatrix(r.matrix);
  }

  async function exportSelected() {
    if (!matrix || !selected.length) return;
    const r = await run("export", () => matrixToCalendar(matrix.id), "Não foi possível enviar ao Calendário.");
    if (r) {
      setMatrix(r.matrix);
      setNotice(r.created
        ? `${r.created} conteúdo(s) no Calendário como rascunho${r.already ? ` (${r.already} já estavam lá)` : ""}. Abra o post no Calendário para anexar a arte e mandar para aprovação.`
        : "Esses conteúdos já estavam no Calendário.");
    }
  }

  const months = matrix ? [1, 2, 3, 4] : [];
  const counts = (p: Platform) => (matrix?.opportunities || []).filter((o) => o.platform === p && o.status !== "descartada").length;

  return <section className="matrixPanel" aria-label="Matriz de conteúdo">
    <div className="matrixToolbar">
      {list.length > 1 ? <label className="matrixPick">Matriz<select value={matrix?.id || ""} disabled={Boolean(busy)} onChange={(e) => void open(e.target.value)}>
        {list.map((m) => <option key={m.id} value={m.id}>Semanas de {weekRange(m.week_start, 1).slice(0, 5)} a {weekRange(m.week_start, 4).slice(-5)} · {m.platforms.map((p) => PLATFORM_LABEL[p]).join(", ")}</option>)}
      </select></label> : null}
      {canManage ? <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => setForm({
        week_start: nextMonday(), platforms: matrix?.platforms?.length ? matrix.platforms : ["instagram"], pillars: [], per_week: 3, focus: "" })}>Gerar matriz</button> : null}
    </div>
    <p className="libHint">A IA monta 4 semanas de oportunidades por plataforma a partir dos pilares do Perfil de Marca e dos dados da marca. Selecione as que valem e envie ao Calendário: entram como rascunho e seguem a aprovação do cliente.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {notice ? <p className="studioOk">{notice}{onOpenCalendar ? <> <button type="button" className="studioLink" onClick={onOpenCalendar}>Abrir o Calendário</button></> : null}</p> : null}
    {busy === "generate" ? <p className="studioOk">Montando a matriz com os pilares e os dados da marca… (até 3 minutos)</p> : null}
    {loading ? <p>Carregando…</p> : null}
    {!loading && !matrix ? <div className="studioEmpty"><p>Nenhuma matriz ainda.{canManage ? <> Clique em <b>Gerar matriz</b>.</> : null}</p>
      {!pillars.length ? <p className="libHint">Esta marca ainda não tem pilares editoriais. Cadastre em <b>IA da marca → Perfil</b> antes de gerar.</p> : null}</div> : null}

    {matrix ? <>
      {matrix.summary ? <p className="matrixSummary">{matrix.summary}</p> : null}
      {(matrix.notes || []).map((n) => <p key={n} className="clipWarn">{n}</p>)}
      <div className="matrixFilters">
        <div className="studioTabs" role="tablist" aria-label="Plataforma">
          <button type="button" role="tab" aria-selected={platform === "todas"} className={platform === "todas" ? "is-active" : ""} onClick={() => setPlatform("todas")}>Todas</button>
          {PLATFORM_ORDER.filter((p) => matrix.platforms.includes(p)).map((p) => <button key={p} type="button" role="tab" aria-selected={platform === p}
            className={platform === p ? "is-active" : ""} onClick={() => setPlatform(p)}>{PLATFORM_LABEL[p]}<span>{counts(p)}</span></button>)}
        </div>
        <label className="studioCheck"><input type="checkbox" checked={showDiscarded} onChange={(e) => setShowDiscarded(e.target.checked)} />Mostrar descartadas{discarded ? ` (${discarded})` : ""}</label>
        {canManage ? <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => void selectVisible()}>Selecionar todas as visíveis</button> : null}
      </div>

      <div className="matrixGridWrap"><table className="matrixGrid">
        <thead><tr><th scope="col">Pilar</th>{months.map((w) => <th key={w} scope="col">Semana {w}<small>{weekRange(matrix.week_start, w)}</small></th>)}</tr></thead>
        <tbody>{rows.map((pillar) => <tr key={pillar}>
          <th scope="row">{pillar}</th>
          {months.map((w) => <td key={w}>{visible.filter((o) => o.pillar === pillar && o.week === w).map((o) =>
            <OpportunityCard key={o.id} op={o} busy={busy} canManage={canManage} onEdit={() => setEditing(o)} onStatus={(s) => void setStatus(o, s)} />)}</td>)}
        </tr>)}</tbody>
      </table></div>
      {!visible.length ? <div className="studioEmpty is-slim"><p>Nada nesta plataforma.</p></div> : null}

      {canManage ? <div className="matrixBar" aria-live="polite">
        <span><b>{selected.length}</b> selecionada(s){exported ? ` · ${exported} já no Calendário` : ""}</span>
        <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !selected.length} onClick={() => void exportSelected()}>
          {busy === "export" ? "Enviando…" : "Enviar ao Calendário"}</button>
        <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => {
          if (window.confirm("Arquivar esta matriz? O que já foi para o Calendário continua lá.")) void run("archive", () => archiveMatrix(matrix.id), "Não foi possível arquivar.").then((r) => { if (r) { setMatrix(null); void load(); } });
        }}>Arquivar matriz</button>
      </div> : null}
    </> : null}

    <Drawer open={Boolean(form)} title="Gerar matriz de conteúdo" description="4 semanas de oportunidades a partir dos pilares do Perfil de Marca." width="lg"
      onClose={() => { if (busy !== "generate") setForm(null); }}>
      {form ? <form className="studioForm" onSubmit={generate}>
        <label>Semana inicial (segunda)<input type="date" required value={form.week_start} onChange={(e) => setForm({ ...form, week_start: e.target.value })} /></label>
        <fieldset><legend>Plataformas</legend>{PLATFORM_ORDER.map((p) => <label key={p} className="studioCheck">
          <input type="checkbox" checked={form.platforms.includes(p)} onChange={() => setForm({ ...form, platforms: form.platforms.includes(p) ? form.platforms.filter((x) => x !== p) : [...form.platforms, p] })} />{PLATFORM_LABEL[p]}</label>)}
          <small className="libHint">Só o Instagram publica sozinho. Nas outras, o post é agendado e, na hora, fica marcado para publicar à mão.</small></fieldset>
        <fieldset><legend>Pilares (vazio = todos)</legend>
          {pillars.length ? pillars.map((p) => <label key={p} className="studioCheck"><input type="checkbox" checked={form.pillars.includes(p)}
            onChange={() => setForm({ ...form, pillars: form.pillars.includes(p) ? form.pillars.filter((x) => x !== p) : [...form.pillars, p] })} />{p}</label>)
            : <p className="studioError">Esta marca ainda não tem pilares editoriais. Cadastre em IA da marca → Perfil.</p>}</fieldset>
        <label>Conteúdos por plataforma por semana<select value={form.per_week} onChange={(e) => setForm({ ...form, per_week: Number(e.target.value) })}>
          {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
        <label>Foco do mês (opcional)<textarea rows={3} maxLength={1000} value={form.focus} onChange={(e) => setForm({ ...form, focus: e.target.value })} placeholder="Ex.: lançamento do kit Oud na semana 2; Black Friday na semana 4" /></label>
        <div className="studioActions"><button type="button" className="ds-button" disabled={busy === "generate"} onClick={() => setForm(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || !form.platforms.length || !pillars.length}>{busy === "generate" ? "Gerando… (até 3 min)" : "Gerar matriz"}</button></div>
      </form> : null}
    </Drawer>

    <OpportunityDrawer key={editing ? `${editing.id}:${editing.updated_at || ""}:${editing.title}` : "none"} op={editing} busy={busy} canManage={canManage} pillars={[...new Set([...(matrix?.pillars || []).map((p) => p.name), ...pillars])]}
      platforms={matrix?.platforms || PLATFORM_ORDER} onClose={() => setEditing(null)}
      onSave={async (patch) => {
        if (!editing) return;
        const r = await run(`e:${editing.id}`, () => updateOpportunity(editing.matrix_id, editing.id, patch), "Não foi possível salvar.");
        if (r) { replace(r.opportunity); setEditing(null); }
      }}
      onRefine={async (instruction) => {
        if (!editing) return;
        const r = await run(`r:${editing.id}`, () => refineOpportunity(editing.matrix_id, editing.id, instruction), "Não foi possível refinar.");
        if (r) { replace(r.opportunity); setEditing(r.opportunity); }
      }} />
  </section>;
}

function OpportunityCard({ op, busy, canManage, onEdit, onStatus }: {
  op: Opportunity; busy: string | null; canManage: boolean; onEdit: () => void; onStatus: (s: "sugerida" | "selecionada" | "descartada") => void;
}) {
  const locked = op.status === "exportada";
  return <article className={`matrixCard is-${op.status}`} aria-label={op.title}>
    <header>
      <span className={`studioChip is-platform is-${op.platform}`}>{PLATFORM_LABEL[op.platform]}</span>
      <span className="studioChip">{STUDIO_FORMATS[op.format]}</span>
      <small>{WEEKDAY_LABEL[op.weekday]}</small>
    </header>
    <button type="button" className="matrixCardTitle" onClick={onEdit}>{op.title}</button>
    {op.hook ? <p className="matrixHook">“{op.hook}”</p> : null}
    {op.guard?.length ? <p className="clipWarn">⚠ {op.guard[0].fix}</p> : null}
    <footer>
      {locked ? <span className="studioChip is-on">No Calendário</span> : canManage ? <>
        <label className="studioCheck"><input type="checkbox" checked={op.status === "selecionada"} disabled={Boolean(busy)}
          onChange={(e) => onStatus(e.target.checked ? "selecionada" : "sugerida")} />Selecionar</label>
        {op.status === "descartada"
          ? <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => onStatus("sugerida")}>Recuperar</button>
          : <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => onStatus("descartada")}>Descartar</button>}
      </> : null}
      {op.edited && !locked ? <span className="studioChip">editada</span> : null}
    </footer>
  </article>;
}

function OpportunityDrawer({ op, busy, canManage, pillars, platforms, onClose, onSave, onRefine }: {
  op: Opportunity | null; busy: string | null; canManage: boolean; pillars: string[]; platforms: Platform[];
  onClose: () => void; onSave: (patch: OpportunityPatch) => Promise<void>; onRefine: (instruction: string) => Promise<void>;
}) {
  // O componente é recriado (key) a cada oportunidade aberta ou refinada: o rascunho nasce dela.
  const [draft, setDraft] = useState<Opportunity | null>(op);
  const [ask, setAsk] = useState("");
  if (!op || !draft) return <Drawer open={false} title="" onClose={onClose}><span /></Drawer>;
  const locked = op.status === "exportada" || !canManage;
  const formats = PLATFORM_FORMATS[draft.platform];
  const set = (patch: Partial<Opportunity>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const changed: OpportunityPatch = {};
  (["platform", "pillar", "week", "weekday", "format", "title", "hook", "angle", "caption_draft", "rationale"] as const).forEach((k) => {
    if (draft[k] !== op[k]) (changed as Record<string, unknown>)[k] = draft[k] ?? "";
  });
  const dirty = Object.keys(changed).length > 0;
  return <Drawer open title={locked && op.status === "exportada" ? "No Calendário" : "Oportunidade"} width="lg" onClose={() => { if (!busy) onClose(); }}
    description={op.status === "exportada" ? "Já virou post no Calendário: edite por lá (arte, aprovação e agendamento)." : "Edite à mão ou peça para a IA refinar."}>
    <form className="studioForm" onSubmit={(e) => { e.preventDefault(); if (dirty) void onSave(changed); }}>
      <div className="studioRow">
        <label>Plataforma<select value={draft.platform} disabled={locked} onChange={(e) => {
          const p = e.target.value as Platform; set({ platform: p, format: PLATFORM_FORMATS[p].includes(draft.format) ? draft.format : PLATFORM_FORMATS[p][0] });
        }}>{PLATFORM_ORDER.filter((p) => platforms.includes(p) || p === draft.platform).map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p]}</option>)}</select></label>
        <label>Formato<select value={draft.format} disabled={locked} onChange={(e) => set({ format: e.target.value as StudioFormat })}>
          {formats.map((f) => <option key={f} value={f}>{STUDIO_FORMATS[f]}</option>)}</select></label>
      </div>
      <div className="studioRow">
        <label>Pilar<select value={draft.pillar} disabled={locked} onChange={(e) => set({ pillar: e.target.value })}>
          {[...new Set([draft.pillar, ...pillars])].map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
        <label>Semana<select value={draft.week} disabled={locked} onChange={(e) => set({ week: Number(e.target.value) })}>
          {[1, 2, 3, 4].map((w) => <option key={w} value={w}>Semana {w}</option>)}</select></label>
        <label>Dia<select value={draft.weekday} disabled={locked} onChange={(e) => set({ weekday: Number(e.target.value) })}>
          {WEEKDAY_LABEL.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></label>
      </div>
      <label>Pauta<input required maxLength={200} value={draft.title} disabled={locked} onChange={(e) => set({ title: e.target.value })} /></label>
      <label>Gancho<input maxLength={400} value={draft.hook || ""} disabled={locked} onChange={(e) => set({ hook: e.target.value })} /></label>
      <label>Ângulo<textarea rows={2} maxLength={600} value={draft.angle || ""} disabled={locked} onChange={(e) => set({ angle: e.target.value })} /></label>
      <label>Rascunho de legenda<textarea rows={6} maxLength={4000} value={draft.caption_draft || ""} disabled={locked} onChange={(e) => set({ caption_draft: e.target.value })} /></label>
      <label>Por que esta pauta<textarea rows={2} maxLength={1200} value={draft.rationale || ""} disabled={locked} onChange={(e) => set({ rationale: e.target.value })} /></label>
      {(op.guard || []).map((g) => <p key={`${g.type}:${g.text}`} className="clipWarn">⚠ {g.fix}</p>)}
      {!locked ? <>
        <div className="pieceAsk">
          <input placeholder="Refinar com a IA (opcional): mais direto, citar o frete grátis, virar carrossel…" value={ask} maxLength={600} onChange={(e) => setAsk(e.target.value)} />
          <button type="button" className="ds-button" disabled={Boolean(busy) || dirty} title={dirty ? "Salve ou descarte as edições antes de refinar" : undefined}
            onClick={() => void onRefine(ask)}>{busy === `r:${op.id}` ? "Refinando…" : "Refinar com a IA"}</button>
        </div>
        <div className="studioActions">
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => (dirty ? setDraft(op) : onClose())}>{dirty ? "Descartar edições" : "Fechar"}</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || !dirty}>{busy === `e:${op.id}` ? "Salvando…" : "Salvar"}</button>
        </div>
      </> : null}
    </form>
  </Drawer>;
}
