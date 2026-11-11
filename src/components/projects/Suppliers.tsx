import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  LINK_STATUS_LABELS, brl, createSupplier, deleteSupplier, eventSuppliersToBudget, linkEventSupplier, listEventSuppliers, listSuppliers,
  unlinkEventSupplier, updateEventSupplier, updateSupplier, type LinkStatus, type Project, type Supplier, type SupplierCategory, type SupplierInput,
  type SupplierLink,
} from "../../app/projects";

type Run = <T>(key: string, fn: () => Promise<T>, fallback: string) => Promise<T | null>;
const EMPTY: SupplierInput = { name: "", category: "outros", contact_name: "", phone: "", email: "", website: "", city: "", price_note: "", rating: null, notes: "" };

/** Aba Fornecedores do Evento: cadastro de quem a marca usa para produzir. A IA do plano usa esta lista (sem contatos). */
export function SupplierBook({ busy, run }: { busy: string | null; run: Run }) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [categories, setCategories] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<(SupplierInput & { id?: string }) | null>(null);
  const [filter, setFilter] = useState<"" | SupplierCategory>("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    let alive = true;
    void run("sup:load", listSuppliers, "Não foi possível carregar os fornecedores.").then((r) => {
      if (!alive) return;
      if (r) { setSuppliers(r.suppliers); setCategories(r.categories); }
      setLoading(false);
    });
    return () => { alive = false; };
  }, [run]);

  const visible = useMemo(() => suppliers.filter((s) => (!filter || s.category === filter)
    && (!search.trim() || `${s.name} ${s.city || ""} ${s.notes || ""}`.toLowerCase().includes(search.trim().toLowerCase()))), [suppliers, filter, search]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const { id, ...input } = editing;
    const payload = { ...input, rating: input.rating || null };
    const r = await run("sup:save", () => (id ? updateSupplier(id, payload) : createSupplier(payload)), "Não foi possível salvar o fornecedor.");
    if (r) { setSuppliers((list) => [...list.filter((s) => s.id !== r.supplier.id), r.supplier].sort((a, b) => a.name.localeCompare(b.name))); setEditing(null); }
  }
  async function remove(s: Supplier) {
    if (!window.confirm(`Apagar ${s.name}? Ele sai também dos eventos em que estava.`)) return;
    const r = await run(`sup:del:${s.id}`, () => deleteSupplier(s.id), "Não foi possível apagar.");
    if (r) setSuppliers((list) => list.filter((x) => x.id !== s.id));
  }
  const set = (k: keyof SupplierInput) => (e: { target: { value: string } }) => setEditing((cur) => cur && { ...cur, [k]: e.target.value });

  return <section className="supBook" aria-label="Fornecedores">
    <div className="studioControls">
      <select value={filter} aria-label="Categoria" onChange={(e) => setFilter(e.target.value as SupplierCategory | "")}>
        <option value="">Todas as categorias</option>{Object.entries(categories).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      <input type="search" value={search} placeholder="Buscar nome, cidade ou observação" aria-label="Buscar fornecedor" onChange={(e) => setSearch(e.target.value)} />
      <button type="button" className="ds-button is-primary" onClick={() => setEditing({ ...EMPTY })}>Novo fornecedor</button>
    </div>
    <p className="libHint">A IA usa estes fornecedores ao montar o plano do evento (nome, categoria, cidade, preço e nota; nunca telefone nem e-mail).</p>
    {editing ? <form className="projNew supForm" onSubmit={save} aria-label={editing.id ? "Editar fornecedor" : "Novo fornecedor"}>
      <label>Nome<input required maxLength={120} value={editing.name || ""} onChange={set("name")} autoFocus /></label>
      <label>Categoria<select value={editing.category || "outros"} onChange={set("category")}>
        {Object.entries(categories).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
      <label>Cidade<input maxLength={120} value={editing.city || ""} onChange={set("city")} placeholder="São Paulo" /></label>
      <label>Faixa de preço<input maxLength={200} value={editing.price_note || ""} onChange={set("price_note")} placeholder="Ex.: R$ 90 por pessoa" /></label>
      <label>Contato<input maxLength={120} value={editing.contact_name || ""} onChange={set("contact_name")} /></label>
      <label>Telefone<input maxLength={40} value={editing.phone || ""} onChange={set("phone")} /></label>
      <label>E-mail<input type="email" maxLength={200} value={editing.email || ""} onChange={set("email")} /></label>
      <label>Site ou Instagram<input maxLength={300} value={editing.website || ""} onChange={set("website")} /></label>
      <label>Nota<select value={editing.rating || ""} onChange={(e) => setEditing({ ...editing, rating: e.target.value ? Number(e.target.value) : null })}>
        <option value="">Sem nota</option>{[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{"★".repeat(n)}</option>)}</select></label>
      <label className="projWide">Observações<textarea rows={2} maxLength={1000} value={editing.notes || ""} onChange={set("notes")} /></label>
      <div className="postBriefingActions projWide">
        <button className="ds-button is-primary" disabled={busy !== null}>{busy === "sup:save" ? "Salvando…" : "Salvar"}</button>
        <button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button>
      </div>
    </form> : null}
    {loading ? <p className="libHint">Carregando…</p> : null}
    {!loading && !suppliers.length && !editing ? <div className="libEmpty"><p>Nenhum fornecedor ainda. Cadastre buffet, foto, vídeo, som e luz, estrutura…</p></div> : null}
    {visible.length ? <table className="projTable supTable"><thead><tr><th>Fornecedor</th><th>Categoria</th><th>Cidade</th><th>Preço</th><th>Contato</th><th /></tr></thead>
      <tbody>{visible.map((s) => <tr key={s.id}>
        <td><b>{s.name}</b>{s.rating ? <small className="supStars"> {"★".repeat(s.rating)}</small> : null}{s.notes ? <small className="libHint"><br />{s.notes}</small> : null}</td>
        <td>{categories[s.category] || s.category}</td><td>{s.city || "—"}</td><td>{s.price_note || "—"}</td>
        <td>{[s.contact_name, s.phone, s.email].filter(Boolean).join(" · ") || "—"}{s.website ? <> · <a href={s.website} target="_blank" rel="noreferrer noopener">site ↗</a></> : null}</td>
        <td className="supActions"><button type="button" className="ds-link" onClick={() => setEditing({ ...s })}>Editar</button>
          <button type="button" className="ds-link" disabled={busy !== null} onClick={() => void remove(s)}>Apagar</button></td>
      </tr>)}</tbody></table> : null}
  </section>;
}

/** Fornecedores do evento: quem faz o quê, status e valor. Contratados com valor vão para o orçamento com um clique. */
export function EventSuppliers({ project, busy, run, onProjectChange }: { project: Project; busy: string | null; run: Run; onProjectChange: (p: Project) => void }) {
  const [links, setLinks] = useState<SupplierLink[] | null>(null);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [categories, setCategories] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<{ supplier_id: string; item: string; value: string }>({ supplier_id: "", item: "", value: "" });

  useEffect(() => {
    void (async () => {
      const [l, s] = await Promise.all([
        run("ev:sup", () => listEventSuppliers(project.id), "Não foi possível carregar os fornecedores do evento."),
        listSuppliers().catch(() => null),
      ]);
      setLinks(l ? l.links : []);
      if (s) { setSuppliers(s.suppliers.filter((x) => x.active)); setCategories(s.categories); }
    })();
  }, [project.id, run]);

  const linkedIds = new Set((links || []).map((l) => l.supplier_id));
  const available = suppliers.filter((s) => !linkedIds.has(s.id));
  const contracted = (links || []).filter((l) => l.status === "contratado" || l.status === "confirmado");
  const total = contracted.reduce((sum, l) => sum + (Number(l.value) || 0), 0);

  async function add() {
    if (!draft.supplier_id) return;
    const r = await run("ev:add", () => linkEventSupplier(project.id, { supplier_id: draft.supplier_id, item: draft.item.trim() || undefined,
      value: draft.value ? Number(draft.value) : null }), "Não foi possível pôr o fornecedor no evento.");
    if (r) { setLinks((l) => [...(l || []), r.link]); setDraft({ supplier_id: "", item: "", value: "" }); }
  }
  async function patch(link: SupplierLink, change: { status?: LinkStatus; value?: number | null; item?: string }) {
    const r = await run(`ev:${link.id}`, () => updateEventSupplier(project.id, link.id, change), "Não foi possível atualizar.");
    if (r) setLinks((l) => (l || []).map((x) => (x.id === link.id ? { ...x, ...r.link, supplier: x.supplier } : x)));
  }
  async function remove(link: SupplierLink) {
    const r = await run(`ev:${link.id}`, () => unlinkEventSupplier(project.id, link.id), "Não foi possível tirar.");
    if (r) setLinks((l) => (l || []).filter((x) => x.id !== link.id));
  }
  async function toBudget() {
    const r = await run("ev:budget", () => eventSuppliersToBudget(project.id), "Não foi possível lançar no orçamento.");
    if (r) onProjectChange(r.project);
  }

  return <div className="evSuppliers">
    {links === null ? <p className="libHint">Carregando…</p> : null}
    {links && !links.length ? <p className="libHint">Nenhum fornecedor neste evento ainda.{!suppliers.length ? " Cadastre na aba Fornecedores." : ""}</p> : null}
    {links?.length ? <table className="projTable"><thead><tr><th>Fornecedor</th><th>O que faz</th><th>Status</th><th className="is-num">Valor (R$)</th><th /></tr></thead>
      <tbody>{links.map((l) => <tr key={l.id} className={`is-${l.status}`}>
        <td><b>{l.supplier.name}</b><small className="libHint"><br />{categories[l.supplier.category] || l.supplier.category}{l.supplier.phone ? ` · ${l.supplier.phone}` : ""}</small></td>
        <td><input defaultValue={l.item || ""} aria-label="O que faz" maxLength={160} onBlur={(e) => { if (e.target.value !== (l.item || "")) void patch(l, { item: e.target.value }); }} /></td>
        <td><select value={l.status} aria-label="Status" disabled={busy !== null} onChange={(e) => void patch(l, { status: e.target.value as LinkStatus })}>
          {(Object.keys(LINK_STATUS_LABELS) as LinkStatus[]).map((k) => <option key={k} value={k}>{LINK_STATUS_LABELS[k]}</option>)}</select></td>
        <td className="is-num"><input type="number" min={0} step={50} defaultValue={l.value ?? ""} aria-label="Valor"
          onBlur={(e) => { const v = e.target.value === "" ? null : Number(e.target.value); if (v !== (l.value ?? null)) void patch(l, { value: v }); }} /></td>
        <td><button type="button" className="ds-link" disabled={busy !== null} onClick={() => void remove(l)}>Tirar</button></td>
      </tr>)}</tbody></table> : null}
    {available.length ? <div className="evSupAdd">
      <select value={draft.supplier_id} aria-label="Fornecedor para o evento" onChange={(e) => setDraft({ ...draft, supplier_id: e.target.value })}>
        <option value="">Pôr fornecedor no evento…</option>
        {available.map((s) => <option key={s.id} value={s.id}>{s.name} · {categories[s.category] || s.category}{s.city ? ` · ${s.city}` : ""}</option>)}</select>
      <input value={draft.item} placeholder="O que faz (ex.: buffet 80 pessoas)" aria-label="O que faz no evento" maxLength={160} onChange={(e) => setDraft({ ...draft, item: e.target.value })} />
      <input type="number" min={0} step={50} value={draft.value} placeholder="Valor" aria-label="Valor cotado" onChange={(e) => setDraft({ ...draft, value: e.target.value })} />
      <button type="button" className="ds-button" disabled={busy !== null || !draft.supplier_id} onClick={() => void add()}>{busy === "ev:add" ? "Pondo…" : "Pôr no evento"}</button>
    </div> : null}
    {contracted.length ? <div className="postBriefingActions">
      <span><b>{contracted.length}</b> contratado(s) · {brl(total)}</span>
      <button type="button" className="ds-button is-primary" disabled={busy !== null || !total} onClick={() => void toBudget()}>
        {busy === "ev:budget" ? "Lançando…" : "Lançar no orçamento"}</button>
    </div> : null}
  </div>;
}
