import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Drawer from "../Drawer";
import { BRAND_PROFILE_SAVED, getBrandProfile, STUDIO_FORMATS, type BrandProfile, type StudioFormat } from "../../app/studio";
import { getActiveClientId } from "../../app/activeClient";
import {
  PLATFORM_FORMATS, PLATFORM_LABEL, PLATFORM_ORDER, WEEKDAY_LABEL, archiveMatrix, createMatrix, getMatrix, listMatrices,
  addOpportunity, createOpportunityContent, deleteOpportunity, matrixToCalendar, refineOpportunity, updateOpportunity,
  type ContentMatrix as Matrix, type MatrixSummary, type Opportunity, type OpportunityCreate, type OpportunityPatch, type Platform,
} from "../../app/contentOps";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const NEW_OPPORTUNITY_ID = "__new_opportunity__";
const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** "16/11 a 22/11" da semana N a partir da segunda inicial. */
function weekRange(weekStart: string, week: number): string {
  const [y, m, d] = weekStart.slice(0, 10).split("-").map(Number);
  const first = new Date(y, m - 1, d + 7 * (week - 1));
  const last = new Date(y, m - 1, d + 7 * (week - 1) + 6);
  return `${pad(first.getDate())}/${pad(first.getMonth() + 1)} a ${pad(last.getDate())}/${pad(last.getMonth() + 1)}`;
}

function opportunityDate(weekStart: string, week: number, weekday: number): string {
  const [year, month, day] = weekStart.slice(0, 10).split("-").map(Number);
  return isoDay(new Date(year, month - 1, day + 7 * (week - 1) + weekday));
}

function slotFromDate(weekStart: string, value: string): { week: number; weekday: number } | null {
  const start = new Date(`${weekStart.slice(0, 10)}T12:00:00`);
  const chosen = new Date(`${value}T12:00:00`);
  const days = Math.round((chosen.getTime() - start.getTime()) / 86_400_000);
  if (days < 0 || days >= 28) return null;
  return { week: Math.floor(days / 7) + 1, weekday: days % 7 };
}

/** Colunas da matriz: formatos (modelo iAgência). Reels e vídeo dividem a coluna. */
const FORMAT_COLUMNS: { key: string; label: string; formats: StudioFormat[] }[] = [
  { key: "carrossel", label: "Carrossel", formats: ["carrossel"] },
  { key: "reels", label: "Reels / Vídeo", formats: ["reels", "video"] },
  { key: "stories", label: "Stories", formats: ["stories"] },
  { key: "imagem", label: "Imagem única", formats: ["imagem"] },
];

function shortDate(weekStart: string, week: number, weekday: number): string {
  const [y, m, d] = opportunityDate(weekStart, week, weekday).split("-").map(Number);
  const date = new Date(y, m - 1, d);
  return `${WEEKDAY_LABEL[weekday].slice(0, 3)} ${pad(date.getDate())}/${pad(date.getMonth() + 1)}`;
}
const hasContent = (op: Opportunity) => Boolean(op.script || op.visual_idea);

type Props = {
  canManage: boolean;
  /** Abre o Calendário depois de exportar (opcional). */
  onOpenCalendar?: () => void;
  /** Abre o cadastro canônico das premissas editoriais. */
  onOpenBrandProfile?: () => void;
};

/**
 * Matriz de Conteúdo (trazida da iAgência): a IA sugere oportunidades por plataforma, pilar e 4 semanas,
 * a partir dos pilares do Perfil de Marca e do contexto da marca. A equipe edita, refina, seleciona e
 * descarta; as selecionadas vão para o Calendário como rascunho e seguem a aprovação de sempre.
 */
export default function ContentMatrix({ canManage, onOpenCalendar, onOpenBrandProfile }: Props) {
  const clientId = getActiveClientId();
  const [list, setList] = useState<MatrixSummary[]>([]);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
      setProfile(profile?.profile || null);
      if (data.matrices?.[0]) setMatrix((await getMatrix(data.matrices[0].id)).matrix);
    } catch (cause) { setError(message(cause, "Não foi possível carregar a matriz.")); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);
  // Perfil salvo na aba Calendário (ou em outra tela): usa o novo na hora, sem recarregar a página.
  useEffect(() => {
    const onSaved = (event: Event) => {
      const next = (event as CustomEvent<BrandProfile>).detail;
      if (next) setProfile(next); else void getBrandProfile().then((r) => setProfile(r?.profile || null)).catch(() => undefined);
    };
    const onFocus = () => { void getBrandProfile().then((r) => { if (getActiveClientId() === clientId) setProfile(r?.profile || null); }).catch(() => undefined); };
    window.addEventListener(BRAND_PROFILE_SAVED, onSaved);
    window.addEventListener("focus", onFocus);
    return () => { window.removeEventListener(BRAND_PROFILE_SAVED, onSaved); window.removeEventListener("focus", onFocus); };
  }, [clientId]);

  async function createContent(op: Opportunity, instruction?: string) {
    const r = await run(`c:${op.id}`, () => createOpportunityContent(op.matrix_id, op.id, instruction), "Não foi possível criar o conteúdo.");
    if (r) { replace(r.opportunity); setEditing((current) => (current && current.id === op.id ? r.opportunity : current)); }
  }
  const replace = (op: Opportunity) => setMatrix((m) => (m ? { ...m, opportunities: m.opportunities.map((o) => (o.id === op.id ? op : o)) } : m));

  async function generate() {
    const r = await run("generate", () => createMatrix(), "Não foi possível gerar a matriz.");
    if (r) {
      setMatrix(r.matrix); setPlatform("todas");
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
    if (!matrix) return [];
    const platforms = matrix.platforms.filter((item) => platform === "todas" || item === platform);
    const pillars = [...new Set([...(matrix.pillars || []).map((item) => item.name), ...visible.map((item) => item.pillar)])];
    return platforms.flatMap((rowPlatform) => pillars.map((pillar) => ({ platform: rowPlatform, pillar })));
  }, [matrix, platform, visible]);
  /** Envia ao Calendário como rascunho. Repetir não duplica (o servidor guarda a pauta de cada oportunidade). */
  async function exportIds(ids: string[], key = "export") {
    if (!matrix || !ids.length) return;
    const r = await run(key, () => matrixToCalendar(matrix.id, ids), "Não foi possível enviar ao Calendário.");
    if (r) {
      setMatrix(r.matrix);
      setNotice(r.created
        ? `${r.created} conteúdo(s) no Calendário como rascunho${r.already ? ` (${r.already} já estavam lá)` : ""}. Abra o post no Calendário para anexar a arte e mandar para aprovação.`
        : "Esses conteúdos já estavam no Calendário.");
    }
  }
  const pending = (items: Opportunity[]) => items.filter((o) => o.status !== "descartada" && o.status !== "exportada").map((o) => o.id);

  async function copyText(op: Opportunity) {
    const text = [op.title, op.hook, op.caption_draft].filter(Boolean).join("\n\n");
    try { await navigator.clipboard.writeText(text); setNotice("Texto copiado."); } catch { /* segue na tela */ }
  }

  const newOpportunity = (rowPlatform: Platform, pillar: string, format: StudioFormat): Opportunity | null => matrix ? {
    id: NEW_OPPORTUNITY_ID, matrix_id: matrix.id, platform: rowPlatform, pillar, week: 1, weekday: 2,
    format, title: "", hook: null, angle: null, caption_draft: null, rationale: null,
    status: "sugerida", edited: true, position: matrix.opportunities.length, calendar_item_id: null, guard: [] } : null;

  const counts = (p: Platform) => (matrix?.opportunities || []).filter((o) => o.platform === p && o.status !== "descartada").length;
  const pillars = (profile?.pillars || []).map((pillar) => pillar.name).filter(Boolean);
  const missingProfile = [!pillars.length ? "pilares editoriais" : "", !(profile?.editorial_platforms || []).length ? "plataformas" : ""].filter(Boolean);

  const period = matrix ? `${weekRange(matrix.week_start, 1).slice(0, 5)} a ${weekRange(matrix.week_start, 4).slice(-5)}` : "";
  const activeCount = (matrix?.opportunities || []).filter((op) => op.status !== "descartada").length;

  return <section className="matrixPanel" aria-label="Matriz de conteúdo">
    <div className="matrixTop">
      <div className="matrixTopInfo">
        {matrix ? <>
          <p className="matrixPeriod">{period}</p>
          <ul className="matrixStats" aria-label="Resumo da matriz">
            <li><b>{matrix.pillars.length}</b> pilares</li>
            <li><b>{activeCount}</b> oportunidades</li>
            <li><b>{exported}</b> no Calendário</li>
          </ul>
        </> : <p className="matrixIntro">A IA monta 4 semanas de pautas por plataforma a partir dos pilares do Perfil da marca. Você escolhe as que valem e envia ao Calendário como rascunho.</p>}
      </div>
      <div className="matrixTopActions">
        {list.length > 1 ? <label className="matrixPick"><span>Matriz</span><select value={matrix?.id || ""} disabled={Boolean(busy)} onChange={(e) => void open(e.target.value)}>
          {list.map((m) => <option key={m.id} value={m.id}>{weekRange(m.week_start, 1).slice(0, 5)} a {weekRange(m.week_start, 4).slice(-5)} · {m.platforms.map((p) => PLATFORM_LABEL[p]).join(", ")}</option>)}
        </select></label> : null}
        {canManage ? <button type="button" className={`ds-button${matrix ? "" : " is-primary"}`} disabled={Boolean(busy) || Boolean(missingProfile.length)} onClick={() => void generate()}>
          {busy === "generate" ? "Gerando…" : matrix ? "Gerar nova matriz" : "Gerar matriz"}</button> : null}
        {canManage && matrix ? <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !pending(visible).length} onClick={() => void exportIds(pending(visible))}
          title="Os conteúdos visíveis que ainda não estão no Calendário viram rascunho">
          {busy === "export" ? "Enviando…" : `Enviar ${platform === "todas" ? "tudo" : PLATFORM_LABEL[platform]} ao Calendário (${pending(visible).length})`}</button> : null}
      </div>
    </div>
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    {notice ? <div className="ds-notice is-positive" role="status"><p className="ds-noticeTitle">{notice}{onOpenCalendar ? <> <button type="button" className="ds-link" onClick={onOpenCalendar}>Abrir o Calendário</button></> : null}</p></div> : null}
    {busy === "generate" ? <div className="ds-notice" role="status"><p className="ds-noticeTitle">Montando a matriz com os pilares e os dados da marca… pode levar até 3 minutos.</p></div> : null}
    {loading ? <p className="matrixMuted">Carregando…</p> : null}
    {!loading && !matrix ? <div className="studioEmpty"><p>Nenhuma matriz ainda.{canManage ? <> Clique em <b>Gerar matriz</b>.</> : null}</p>
      {missingProfile.length ? <p className="libHint">Falta configurar {missingProfile.join(" e ")} no Perfil da marca.
        {onOpenBrandProfile ? <> <button type="button" className="studioLink" onClick={onOpenBrandProfile}>Abrir Perfil da marca</button></> : null}</p> : null}</div> : null}

    {matrix ? <>
      {matrix.summary || (matrix.notes || []).length ? <div className="matrixBrief">
        {matrix.summary ? <div className="matrixSummary"><span>Direção do mês</span><p>{matrix.summary}</p></div> : null}
        {(matrix.notes || []).length ? <ul className="matrixNotes">{(matrix.notes || []).map((n) => <li key={n}>{n}</li>)}</ul> : null}
      </div> : null}

      <section className="tacticalMatrix" aria-label="Matriz Tática de Conteúdo">
        <div className="tacticalPlatforms" role="tablist" aria-label="Plataforma">
          <button type="button" role="tab" aria-selected={platform === "todas"} className={platform === "todas" ? "is-active" : ""} onClick={() => setPlatform("todas")}>Todas</button>
          {PLATFORM_ORDER.filter((p) => matrix.platforms.includes(p)).map((p) => <button key={p} type="button" role="tab" aria-selected={platform === p}
            className={platform === p ? "is-active" : ""} onClick={() => setPlatform(p)}>{PLATFORM_LABEL[p]}<span>{counts(p)}</span></button>)}
          <label className="tacticalDiscarded"><input type="checkbox" checked={showDiscarded} onChange={(e) => setShowDiscarded(e.target.checked)} />Mostrar descartadas{discarded ? ` (${discarded})` : ""}</label>
        </div>

        <p className="matrixHint">Cada pauta já vem com a data sugerida. Clique numa pauta para criar com a IA a legenda, o roteiro e a ideia de imagem.</p>
        <div className="matrixGridWrap"><table className="matrixGrid tacticalGrid">
          <thead><tr><th scope="col">Canal</th><th scope="col">Pilar</th>
            {FORMAT_COLUMNS.map((col) => <th key={col.key} scope="col">{col.label}</th>)}</tr></thead>
          {matrix.platforms.filter((p) => platform === "todas" || p === platform).map((rowPlatform) => {
            const pillarRows = rows.filter((row) => row.platform === rowPlatform);
            const platformOps = visible.filter((o) => o.platform === rowPlatform);
            return <tbody key={rowPlatform} className={`tacticalGroup is-${rowPlatform}`}>{pillarRows.map((row, index) => <tr key={`${row.platform}:${row.pillar}`}>
              {index === 0 ? <th scope="rowgroup" rowSpan={pillarRows.length} className="tacticalChannel">
                <span className={`studioChip is-platform is-${rowPlatform}`}>{PLATFORM_LABEL[rowPlatform]}</span>
                <small>{PLATFORM_FORMATS[rowPlatform].map((f) => STUDIO_FORMATS[f]).join(" · ")}</small>
                {canManage && pending(platformOps).length ? <button type="button" className="studioLink" disabled={Boolean(busy)}
                  onClick={() => void exportIds(pending(platformOps), `export:${rowPlatform}`)}>
                  {busy === `export:${rowPlatform}` ? "Enviando…" : `Enviar ${PLATFORM_LABEL[rowPlatform]} ao Calendário (${pending(platformOps).length})`}</button> : null}
              </th> : null}
              <th scope="row" className="tacticalPillar">{row.pillar}</th>
              {FORMAT_COLUMNS.map((col) => {
                const supported = col.formats.filter((f) => PLATFORM_FORMATS[row.platform].includes(f));
                if (!supported.length) return <td key={col.key} className="is-unavailable" aria-label={`${PLATFORM_LABEL[row.platform]} não tem ${col.label}`}><span className="matrixNa">—</span></td>;
                const cell = visible.filter((o) => o.platform === row.platform && o.pillar === row.pillar && col.formats.includes(o.format))
                  .sort((a, b) => a.week * 7 + a.weekday - (b.week * 7 + b.weekday));
                return <td key={col.key}>{cell.map((op) =>
                  <OpportunityCard key={op.id} op={op} weekStart={matrix.week_start} busy={busy} canManage={canManage} onEdit={() => setEditing(op)} onStatus={(status) => void setStatus(op, status)}
                    onCopy={() => void copyText(op)} onExport={() => void exportIds([op.id], `export:${op.id}`)}
                    onCreate={() => void createContent(op)}
                    onTitle={async (title) => { const result = await run(`e:${op.id}`, () => updateOpportunity(op.matrix_id, op.id, { title }), "Não foi possível salvar a pauta."); if (result) replace(result.opportunity); return Boolean(result); }} />)}
                  {canManage ? <button type="button" className="matrixCellAdd" aria-label={`Adicionar ${col.label} em ${PLATFORM_LABEL[row.platform]}, ${row.pillar}`}
                    onClick={() => setEditing(newOpportunity(row.platform, row.pillar, supported[0]))}>+</button> : null}</td>;
              })}
            </tr>)}</tbody>;
          })}
        </table></div>
        {!rows.length ? <div className="studioEmpty is-slim"><p>Nenhuma oportunidade nesta plataforma.</p></div> : null}
      </section>

      {canManage ? <div className="matrixBar" aria-live="polite">
        <span><b>{selected.length}</b> selecionada(s) · marque as pautas e envie só elas</span>
        <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !selected.length} onClick={() => void exportIds(selected.map((o) => o.id))}>
          {busy === "export" ? "Enviando…" : `Enviar selecionadas (${selected.length})`}</button>
        {onOpenCalendar && exported ? <button type="button" className="ds-link is-quiet" onClick={onOpenCalendar}>Abrir o Calendário</button> : null}
        <button type="button" className="ds-link is-quiet" disabled={Boolean(busy)} onClick={() => {
          if (window.confirm("Arquivar esta matriz? O que já foi para o Calendário continua lá.")) void run("archive", () => archiveMatrix(matrix.id), "Não foi possível arquivar.").then((r) => { if (r) { setMatrix(null); void load(); } });
        }}>Arquivar matriz</button>
      </div> : null}
    </> : null}

    <OpportunityDrawer key={editing ? `${editing.id}:${editing.updated_at || ""}:${editing.title}` : "none"} op={editing} busy={busy} canManage={canManage} pillars={[...new Set([...(matrix?.pillars || []).map((p) => p.name), ...pillars])]}
      platforms={matrix?.platforms || PLATFORM_ORDER} weekStart={matrix?.week_start || ""} isNew={editing?.id === NEW_OPPORTUNITY_ID} onClose={() => setEditing(null)}
      onSave={async (patch) => {
        if (!editing) return;
        if (editing.id === NEW_OPPORTUNITY_ID) {
          const draft = { ...editing, ...patch };
          const input: OpportunityCreate = { platform: draft.platform, pillar: draft.pillar, week: draft.week, weekday: draft.weekday,
            format: draft.format, title: draft.title, hook: draft.hook, angle: draft.angle,
            caption_draft: draft.caption_draft, rationale: draft.rationale, script: draft.script || null, visual_idea: draft.visual_idea || null };
          const r = await run(`e:${NEW_OPPORTUNITY_ID}`, () => addOpportunity(editing.matrix_id, input), "Não foi possível acrescentar a oportunidade.");
          if (r) { setMatrix((current) => current ? { ...current, opportunities: [...current.opportunities, r.opportunity] } : current); setEditing(null); }
        } else {
          const r = await run(`e:${editing.id}`, () => updateOpportunity(editing.matrix_id, editing.id, patch), "Não foi possível salvar.");
          if (r) { replace(r.opportunity); setEditing(null); }
        }
      }}
      onRefine={async (instruction) => {
        if (!editing) return;
        const r = await run(`r:${editing.id}`, () => refineOpportunity(editing.matrix_id, editing.id, instruction), "Não foi possível refinar.");
        if (r) { replace(r.opportunity); setEditing(r.opportunity); }
      }} onCreate={async (instruction) => { if (editing) await createContent(editing, instruction); }} onDelete={async () => {
        if (!editing || editing.id === NEW_OPPORTUNITY_ID) { setEditing(null); return; }
        if (!window.confirm("Excluir esta oportunidade da matriz?")) return;
        const r = await run(`d:${editing.id}`, () => deleteOpportunity(editing.matrix_id, editing.id), "Não foi possível excluir a oportunidade.");
        if (r) { setMatrix((current) => current ? { ...current, opportunities: current.opportunities.filter((op) => op.id !== editing.id) } : current); setEditing(null); }
      }} />
  </section>;
}

function OpportunityCard({ op, weekStart, busy, canManage, onEdit, onStatus, onTitle, onCopy, onExport, onCreate }: {
  op: Opportunity; weekStart: string; busy: string | null; canManage: boolean; onEdit: () => void; onStatus: (s: "sugerida" | "selecionada" | "descartada") => void;
  onTitle: (title: string) => Promise<boolean>; onCopy: () => void; onExport: () => void; onCreate: () => void;
}) {
  const locked = op.status === "exportada";
  return <article className={`matrixCard tacticalCell is-${op.status}`} aria-label={op.title}>
    <header>
      <small className="matrixDate" title="Data sugerida para publicar">{shortDate(weekStart, op.week, op.weekday)}</small>
      {op.format === "video" ? <span className="studioChip">{STUDIO_FORMATS[op.format]}</span> : null}
      <span className="tacticalCellActions">
        <button type="button" title="Copiar" aria-label={`Copiar ${op.title}`} onClick={onCopy}>⧉</button>
        <button type="button" title="Legenda, roteiro e detalhes" aria-label={`Detalhes de ${op.title}`} onClick={onEdit}>✎</button>
        {canManage && !locked && op.status !== "descartada" ? <button type="button" title="Enviar ao Calendário" aria-label={`Enviar ${op.title} ao Calendário`}
          disabled={Boolean(busy)} onClick={onExport}>➤</button> : null}
      </span>
    </header>
    {canManage ? <InlineTitle key={op.title} op={op} disabled={Boolean(busy)} onSave={onTitle} />
      : <p className="matrixCardText">{op.title}</p>}
    {op.guard?.length ? <p className="clipWarn">⚠ {op.guard[0].fix}</p> : null}
    {hasContent(op) ? <button type="button" className="matrixContentReady" onClick={onEdit}>✓ Legenda, roteiro e ideia de imagem</button>
      : canManage && op.status !== "exportada" && op.status !== "descartada"
        ? <button type="button" className="matrixCreate" disabled={Boolean(busy)} onClick={onCreate}>{busy === `c:${op.id}` ? "Criando…" : "✦ Criar conteúdo"}</button> : null}
    <footer>
      {locked ? <span className="studioChip is-on">✓ No Calendário</span> : canManage ? <>
        <label className="studioCheck"><input type="checkbox" checked={op.status === "selecionada"} disabled={Boolean(busy)}
          onChange={(e) => onStatus(e.target.checked ? "selecionada" : "sugerida")} />Selecionar</label>
        {op.status === "descartada"
          ? <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => onStatus("sugerida")}>Recuperar</button>
          : <button type="button" className="studioLink" disabled={Boolean(busy)} onClick={() => onStatus("descartada")}>Descartar</button>}
      </> : null}
    </footer>
  </article>;
}

/** Texto da pauta editado no próprio card: clica, escreve e sai (ou Enter) para salvar; Esc desfaz. */
function InlineTitle({ op, disabled, onSave }: { op: Opportunity; disabled: boolean; onSave: (title: string) => Promise<boolean> }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const fit = () => { const el = ref.current; if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; } };
  useEffect(fit, []);
  const save = () => {
    const field = ref.current; if (!field) return;
    const next = field.value.replace(/\s+/g, " ").trim();
    if (!next) { field.value = op.title; fit(); return; }
    if (next !== op.title) void onSave(next).then((saved) => { if (!saved && ref.current) { ref.current.value = op.title; fit(); } });
  };
  return <textarea ref={ref} className="matrixCellEditor" aria-label={`Editar texto da pauta ${op.title}`} rows={1} maxLength={200}
    defaultValue={op.title} disabled={disabled} title="Clique para editar o texto" onInput={fit} onBlur={save}
    onKeyDown={(e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.blur(); }
      if (e.key === "Escape") { e.currentTarget.value = op.title; fit(); e.currentTarget.blur(); }
    }} />;
}

function OpportunityDrawer({ op, busy, canManage, pillars, platforms, weekStart, isNew, onClose, onSave, onRefine, onCreate, onDelete }: {
  op: Opportunity | null; busy: string | null; canManage: boolean; pillars: string[]; platforms: Platform[];
  weekStart: string; isNew: boolean; onClose: () => void; onSave: (patch: OpportunityPatch) => Promise<void>;
  onRefine: (instruction: string) => Promise<void>; onCreate: (instruction: string) => Promise<void>; onDelete: () => Promise<void>;
}) {
  // O componente é recriado (key) a cada oportunidade aberta ou refinada: o rascunho nasce dela.
  const [draft, setDraft] = useState<Opportunity | null>(op);
  const [ask, setAsk] = useState("");
  if (!op || !draft) return <Drawer open={false} title="" onClose={onClose}><span /></Drawer>;
  const locked = op.status === "exportada" || !canManage;
  const formats = PLATFORM_FORMATS[draft.platform];
  const set = (patch: Partial<Opportunity>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const changed: OpportunityPatch = {};
  (["platform", "pillar", "week", "weekday", "format", "title", "hook", "angle", "caption_draft", "rationale", "script", "visual_idea"] as const).forEach((k) => {
    if (draft[k] !== op[k]) (changed as Record<string, unknown>)[k] = draft[k] ?? "";
  });
  const dirty = Object.keys(changed).length > 0;
  return <Drawer open title={isNew ? "Nova pauta" : locked && op.status === "exportada" ? "No Calendário" : "Pauta"} width="lg" onClose={() => { if (!busy) onClose(); }}
    description={op.status === "exportada" ? "Já virou post no Calendário: edite por lá (arte, aprovação e agendamento)." : "Crie o conteúdo com a IA ou edite à mão. Depois envie ao Calendário para publicar."}>
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
        <label>Data sugerida para publicar<input type="date" value={opportunityDate(weekStart, draft.week, draft.weekday)} disabled={locked}
          min={weekStart.slice(0, 10)} max={opportunityDate(weekStart, 4, 6)} onChange={(e) => { const slot = slotFromDate(weekStart, e.target.value); if (slot) set(slot); }} /></label>
      </div>
      <label>Pauta<input required maxLength={200} value={draft.title} disabled={locked} onChange={(e) => set({ title: e.target.value })} /></label>
      <label>Gancho<input maxLength={400} value={draft.hook || ""} disabled={locked} onChange={(e) => set({ hook: e.target.value })} /></label>
      <label>Ângulo<textarea rows={2} maxLength={600} value={draft.angle || ""} disabled={locked} onChange={(e) => set({ angle: e.target.value })} /></label>
      {!locked && !isNew ? <div className="matrixCreatePanel">
        <div><b>Criar o conteúdo com a IA</b><small>Legenda, roteiro ({draft.format === "carrossel" ? "texto de cada slide" : draft.format === "stories" ? "telas" : draft.format === "imagem" ? "texto da arte" : "cenas"}) e ideia de imagem, no tom da marca. Use o campo abaixo para pedir algo específico.</small></div>
        <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || dirty} title={dirty ? "Salve ou descarte as edições antes" : undefined}
          onClick={() => void onCreate(ask)}>{busy === `c:${op.id}` ? "Criando…" : hasContent(op) ? "✦ Criar de novo" : "✦ Criar conteúdo"}</button>
      </div> : null}
      <label>Legenda<textarea rows={6} maxLength={4000} value={draft.caption_draft || ""} disabled={locked} onChange={(e) => set({ caption_draft: e.target.value })} /></label>
      <label>Roteiro<textarea rows={7} maxLength={4000} value={draft.script || ""} disabled={locked} placeholder="Cenas do vídeo, slides do carrossel, telas do Stories ou texto da arte" onChange={(e) => set({ script: e.target.value })} /></label>
      <label>Ideia de imagem<textarea rows={4} maxLength={2000} value={draft.visual_idea || ""} disabled={locked} placeholder="Direção da arte: cena, enquadramento, cores, texto na arte" onChange={(e) => set({ visual_idea: e.target.value })} /></label>
      {op.briefing && Object.keys(op.briefing).length ? <div className="postFromMatrix postBriefing">
        <b>Briefing da peça</b>
        {([["summary", "Resumo"], ["objective", "Objetivo"], ["key_message", "Mensagem central"], ["tone", "Tom"], ["target_audience", "Público"]] as const)
          .map(([k, label]) => op.briefing?.[k] ? <p key={k}><b>{label}:</b> {op.briefing[k]}</p> : null)}
        {op.briefing.deliverables?.length ? <p><b>Entregáveis:</b> {op.briefing.deliverables.join("; ")}</p> : null}
        {op.briefing.tech_requirements?.length ? <p><b>Requisitos técnicos:</b> {op.briefing.tech_requirements.join("; ")}</p> : null}
        <small>Vai junto para a pauta do Calendário (lá dá para editar ou refazer).</small>
      </div> : null}
      <label>Por que esta pauta<textarea rows={2} maxLength={1200} value={draft.rationale || ""} disabled={locked} onChange={(e) => set({ rationale: e.target.value })} /></label>
      {(op.guard || []).map((g) => <p key={`${g.type}:${g.text}`} className="clipWarn">⚠ {g.fix}</p>)}
      {!locked ? <>
        {!isNew ?
        <div className="pieceAsk">
          <input placeholder="Pedido para a IA (opcional): mais direto, citar o frete grátis, tom mais leve…" value={ask} maxLength={600} onChange={(e) => setAsk(e.target.value)} />
          <button type="button" className="ds-button" disabled={Boolean(busy) || dirty} title={dirty ? "Salve ou descarte as edições antes de refinar" : "Troca a ideia da pauta (título, gancho, ângulo)"}
            onClick={() => void onRefine(ask)}>{busy === `r:${op.id}` ? "Refinando…" : "Trocar a ideia"}</button>
        </div> : null}
        <div className="studioActions">
          {!isNew ? <button type="button" className="studioLink is-danger" disabled={Boolean(busy)} onClick={() => void onDelete()}>Excluir</button> : null}
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => (dirty && !isNew ? setDraft(op) : onClose())}>{dirty && !isNew ? "Descartar edições" : "Fechar"}</button>
          <button className="ds-button is-primary" disabled={Boolean(busy) || !draft.title.trim() || (!dirty && !isNew)}>{busy === `e:${op.id}` ? "Salvando…" : "Salvar"}</button>
        </div>
      </> : null}
    </form>
  </Drawer>;
}
